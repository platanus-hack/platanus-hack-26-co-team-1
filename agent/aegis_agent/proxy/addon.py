from __future__ import annotations

import json
import os
import threading
import time

from mitmproxy import http

from ..detect import inyeccion, model
from ..detect.owners import exento
from ..detect.payload import (
    ScanResult,
    scan_payload,
    texto_de_respuesta,
    texto_para_inyeccion,
)
from ..domains import DomainClient
from ..detect.types import Finding
from ..events import DEFAULT_QUEUE, build_event, enqueue
from ..lessons import lesson_for, pedir_en_segundo_plano
from ..policy import (
    Classification,
    Policy,
    classify,
    decide,
    decidir_sobre,
    looks_like_ai_api,
)
from ..policy_store import cargar as cargar_politica
from ..policy_store import refrescar_en_segundo_plano
from ..procesos import DESCONOCIDO, Proceso, del_puerto
from ..sensor import SensorDePuntosCiegos
from ..signals import SignalCollector
from . import blockpage

# Solo estos metodos llevan payload hacia afuera. Un GET a una IA aprobada no se
# inspecciona: no hay nada que inspeccionar y si el costo de hacerlo.
METHODS_WITH_PAYLOAD = frozenset({"POST", "PUT", "PATCH"})

# Lo que alcanza para decidir si un request tiene forma de llamada a un modelo.
# Leer mas es gastar en el 97% del trafico que no va a ninguna IA.
PREVIEW_BYTES = 4000

_HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}
_JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}

_WS_REDACTED = "[Aegis bloqueo este mensaje: contenia informacion sensible]"

# Cada cuanto se vuelve a registrar el uso de una misma herramienta no aprobada.
PAUSA_USO = 600

# Cada cuanto mira el sensor la tabla de conexiones. Va lento a proposito: no
# esta en el camino de ninguna decision y no tiene por que competir por CPU.
INTERVALO_DEL_SENSOR = 10


def _ruta_del_proceso(pid: int) -> str:
    try:
        import psutil

        ruta = psutil.Process(pid).exe()
    except Exception:
        ruta = ""
    return ruta


def _is_navigation(flow: http.HTTPFlow) -> bool:
    """Distingue abrir una pagina de una llamada interna de la aplicacion.

    Contestarle a un fetch con una pagina HTML deja a la aplicacion girando para
    siempre: recibe algo que no sabe interpretar y no muestra ningun error. El
    usuario se queda sin entender que paso, que es exactamente lo que Aegis
    existe para evitar.
    """

    destino = flow.request.headers.get("Sec-Fetch-Dest", "")
    if destino:
        navegacion = destino == "document"
    else:
        acepta = flow.request.headers.get("Accept", "")
        navegacion = "text/html" in acepta and "application/json" not in acepta
    return navegacion


def _deny(flow: http.HTTPFlow, html: str, mensaje: str, cabeceras: dict) -> None:
    """Responde con la pagina o con un error que la aplicacion pueda mostrar."""

    if _is_navigation(flow):
        cuerpo = html.encode("utf-8")
        tipo = _HTML_HEADERS
    else:
        cuerpo = json.dumps(
            {
                "error": {
                    "type": "aegis_blocked",
                    "message": mensaje,
                    "code": "blocked_by_aegis",
                }
            },
            ensure_ascii=False,
        ).encode("utf-8")
        tipo = _JSON_HEADERS
    flow.response = http.Response.make(403, cuerpo, {**tipo, **cabeceras})


class Aegis:
    def __init__(self) -> None:
        # La politica llega del archivo local, no de constantes en el codigo: es
        # lo que permite que la empresa la edite desde el panel. Se lee de disco
        # y nunca de la red, asi que sin conexion se aplica la ultima conocida
        # (ADR 0003). El refresco deja el archivo listo para el proximo arranque.
        self.policy = cargar_politica()
        self.user_id = os.environ.get("AEGIS_USER", "u_demo")
        self.area = os.environ.get("AEGIS_AREA", "marketing")
        self.queue = DEFAULT_QUEUE
        # La base colaborativa extiende el catalogo en caliente. Se consulta solo
        # contra el cache local: la red nunca esta en el camino de la decision.
        self.domains = DomainClient(
            enabled=os.environ.get("AEGIS_BACKEND_DISABLED") != "1"
        )
        # Senales de comportamiento: lo unico que encuentra al shadow AI que no
        # esta en ninguna lista y que tampoco parece nada por su nombre.
        self.signals = SignalCollector()
        self._ultimo_uso: dict[str, float] = {}
        self._lock_uso = threading.Lock()
        # Que aplicacion abrio cada conexion. Se resuelve una vez por
        # conexion TCP y no por request: leer la tabla del sistema cuesta
        # unos 3 ms, que es barato una vez y caro mil veces. Con keep-alive,
        # una sesion entera de un CLI paga una sola lectura.
        self._procesos: dict[str, Proceso] = {}
        # El modelo tarda unos ocho segundos en cargar. Hacerlo en el primer
        # envio significa que la primera persona que abre un chat espera todo eso
        # con el request frenado, y llega a la conclusion correcta: que Aegis
        # rompe las cosas. Se carga aca, mientras nadie esta esperando.
        if model.habilitado():
            threading.Thread(target=model.cargar, daemon=True).start()

        if os.environ.get("AEGIS_BACKEND_DISABLED") != "1":
            refrescar_en_segundo_plano(
                os.environ.get("AEGIS_BACKEND", "http://127.0.0.1:8686"),
                self.policy.tenant_id,
            )

        # Capa D: lo que Aegis no puede ver. Una aplicacion con su propio stack
        # de red no consulta el proxy y su trafico no pasa por aca nunca. El
        # sensor no lo intercepta, lo hace visible.
        self.sensor = SensorDePuntosCiegos(
            pid_del_proxy=os.getpid(),
            es_ia=lambda host: classify(host, self.policy) != "non_ai",
        )
        self._puntos_ciegos_cortados: set[str] = set()
        if os.environ.get("AEGIS_SENSOR") != "0":
            threading.Thread(target=self._vigilar, daemon=True).start()

    def _vigilar(self) -> None:
        """Mira la tabla de conexiones cada tanto, lejos del camino critico.

        Primero resuelve el catalogo, que tarda unos segundos y se hace una sola
        vez. Despues cada pasada cuesta milisegundos porque ya no consulta nada.
        """

        from ..catalog import AI_DOMAINS

        self.sensor.cargar_catalogo(sorted(AI_DOMAINS))
        while True:
            try:
                for punto in self.sensor.revisar():
                    self._reportar_punto_ciego(punto)
            except Exception:
                # El sensor es visibilidad, no proteccion: que falle no puede
                # llevarse puesto al proxy, que es lo que si esta protegiendo.
                pass
            time.sleep(INTERVALO_DEL_SENSOR)

    def _reportar_punto_ciego(self, punto) -> None:
        """Lo registra y, si la empresa lo pidio, le saca la ruta directa.

        Aca no se puede mirar el contenido: si la aplicacion esquivo el proxy, su
        trafico va cifrado y directo. La decision del administrador no es sobre
        el dato sino sobre el punto ciego en si.
        """

        cortar = self.policy.blind_spot_action == "block"
        if cortar and punto.proceso not in self._puntos_ciegos_cortados:
            self._puntos_ciegos_cortados.add(punto.proceso)
            threading.Thread(
                target=self._cortar_ruta_directa, args=(punto,), daemon=True
            ).start()

        hallazgo = Finding(
            rule_id="punto_ciego",
            category="policy",
            severity="high",
            confidence=1.0,
            evidence=f"<{punto.proceso}>"[:32],
            start=0,
            end=0,
        )
        self._record(
            host=punto.host,
            classification="ai_unapproved",
            finding=hallazgo,
            action="blocked" if cortar else "warned",
            payload_bytes=0,
            truncated=False,
            proceso=punto.proceso,
        )

    def _cortar_ruta_directa(self, punto) -> None:
        from ..install import firewall

        ruta = _ruta_del_proceso(punto.pid)
        if ruta:
            firewall.bloquear_programa(ruta, self.sensor.ips_conocidas())

    def client_connected(self, client) -> None:
        """Resuelve la aplicacion al abrir la conexion, fuera del camino critico.

        Hacerlo aca y no en request() es lo que mantiene la atribucion gratis:
        el request no espera por una lectura de la tabla de conexiones.
        """

        try:
            puerto = client.peername[1]
        except (AttributeError, IndexError, TypeError):
            puerto = 0
        if puerto:
            self._procesos[client.id] = del_puerto(puerto)

    def client_disconnected(self, client) -> None:
        self._procesos.pop(client.id, None)

    def _proceso_de(self, flow: http.HTTPFlow) -> Proceso:
        try:
            conocido = self._procesos.get(flow.client_conn.id)
        except AttributeError:
            conocido = None
        return conocido or Proceso()

    def request(self, flow: http.HTTPFlow) -> None:
        # Otro addon (el upstream simulado de los tests) pudo responder antes.
        if flow.response is None:
            self._handle(flow)

    def websocket_message(self, flow) -> None:
        """Los chats de IA mandan los prompts por websocket, no solo por POST.

        Sin este hook, todo el motor se esquiva abriendo la version web del chat.
        """

        message = flow.websocket.messages[-1]
        if message.from_client:
            host = flow.request.pretty_host
            classification = classify(host, self.policy)
            if classification not in ("passthrough", "non_ai"):
                result = scan_payload(message.content if isinstance(message.content, bytes) else str(message.content).encode())
                if result.findings:
                    worst = result.findings[0]
                    message.content = _WS_REDACTED.encode("utf-8")
                    self._record(
                        host=host,
                        classification=classification,
                        finding=worst,
                        action="blocked",
                        payload_bytes=len(message.content),
                        truncated=result.truncated,
                        proceso=self._proceso_de(flow).nombre,
                    )

    def response(self, flow: http.HTTPFlow) -> None:
        """Mira como responde el servidor, no solo que le pidieron.

        El streaming por eventos es la huella mas fiable de un modelo: casi
        ningun servicio normal responde asi y casi todos los chats con modelo si.
        """

        host = flow.request.pretty_host
        clasificacion = classify(host, self.policy)
        if clasificacion == "non_ai" and flow.response is not None:
            self.signals.observe_response(
                host, flow.response.headers.get("Content-Type", "")
            )
            self._maybe_classify(host)
        else:
            if flow.response is not None and clasificacion not in ("passthrough", "non_ai"):
                self._mirar_inyeccion_en_la_respuesta(flow, host, clasificacion)

    def _mirar_inyeccion_en_la_respuesta(
        self, flow: http.HTTPFlow, host: str, clasificacion: Classification
    ) -> None:
        """Lo que el modelo devuelve tambien es texto que alguien va a obedecer.

        Nunca corta. Cuando la respuesta llega, el modelo ya la genero; dejar a
        la herramienta esperando un cuerpo que no va a llegar rompe la sesion sin
        evitar nada. Lo que si hace es registrar el intento, que es lo que
        convierte una sospecha en algo que la empresa puede mirar.
        """

        try:
            cuerpo = flow.response.get_content(strict=False) or b""
        except Exception:
            # Una respuesta con un encoding roto no puede tumbar el proxy.
            cuerpo = b""

        # Se extrae el texto del sobre JSON antes de mirarlo: una orden puesta
        # al principio de la respuesta empieza justo despues de una comilla, y
        # la regla exige que abra una oracion.
        texto = texto_de_respuesta(cuerpo)
        for hallazgo in inyeccion.buscar(texto, direccion="respuesta"):
            self._record(
                host=host,
                classification=clasificacion,
                finding=hallazgo,
                action="warned",
                payload_bytes=len(cuerpo),
                truncated=len(cuerpo) > inyeccion.MAX_CARACTERES,
                proceso=self._proceso_de(flow).nombre,
            )

    def _maybe_classify(self, host: str) -> None:
        if self.signals.should_classify(host):
            self.domains.request_classification(host)

    def _handle(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        classification = classify(host, self.policy)

        if classification == "non_ai":
            compartido = self.domains.cached(host)
            if compartido == "ai_unapproved":
                classification = "ai_unapproved"

        corta_destino = (
            classification == "ai_unapproved"
            and self.policy.unapproved_ai_action == "block_destination"
        )
        if corta_destino:
            self._block_destination(flow, host, classification)
        else:
            if classification == "ai_unapproved":
                # Aunque se deje pasar, el uso de una herramienta no aprobada es
                # justamente lo que la empresa necesita ver en el panel: con que
                # aplicacion la usan es la otra mitad del dato.
                self._registrar_uso(host, classification, self._proceso_de(flow).nombre)
            if flow.request.method in METHODS_WITH_PAYLOAD and classification != "passthrough":
                self._inspect(flow, host, classification)

    def _block_destination(
        self, flow: http.HTTPFlow, host: str, classification: Classification
    ) -> None:
        approved = sorted(self.policy.approved_ai)
        self._record(
            host=host,
            classification=classification,
            finding=None,
            action="blocked",
            payload_bytes=len(flow.request.raw_content or b""),
            truncated=False,
            proceso=self._proceso_de(flow).nombre,
        )
        _deny(
            flow,
            blockpage.destination_blocked(host, approved),
            f"Aegis bloqueo la conexion: {host} no es una herramienta de IA "
            f"aprobada por tu empresa. Usa {', '.join(approved)}.",
            {"X-Aegis-Action": "block_destination"},
        )

    def _inyeccion_en_el_envio(
        self,
        flow: http.HTTPFlow,
        host: str,
        classification: Classification,
        body: bytes,
        proceso: Proceso,
    ) -> bool:
        """Contenido envenenado que el agente esta por darle al modelo.

        Devuelve True si corto el envio, para que no se siga inspeccionando algo
        que ya no va a salir.

        Este es el caso util de los dos: se avisa ANTES de que el modelo lea la
        orden. En la respuesta ya es tarde para prevenir, solo queda registrar.
        """

        hallazgos = inyeccion.buscar(texto_para_inyeccion(body), direccion="envio")
        corto = False
        if hallazgos:
            peor = hallazgos[0]
            corto = self.policy.injection_action == "block"
            self._record(
                host=host,
                classification=classification,
                finding=peor,
                action="blocked" if corto else "warned",
                payload_bytes=len(body),
                truncated=False,
                proceso=proceso.nombre,
            )
            if corto:
                leccion = lesson_for(peor.rule_id)
                _deny(
                    flow,
                    blockpage.content_blocked(
                        host,
                        peor.rule_id,
                        peor.evidence,
                        leccion,
                        aprobada=classification == "ai_approved",
                    ),
                    f"Aegis bloqueo el envio: {leccion['title']}. {leccion['what_to_do']}",
                    {
                        "X-Aegis-Action": "block_content",
                        "X-Aegis-Rule": peor.rule_id,
                    },
                )
        return corto

    def _inspect(
        self, flow: http.HTTPFlow, host: str, classification: Classification
    ) -> None:
        # get_content decodifica gzip/brotli. Con raw_content, comprimir el body
        # alcanzaria para pasar cualquier secreto sin que ninguna regla lo vea.
        body = flow.request.get_content(strict=False) or b""
        query = str(flow.request.query) if flow.request.query else ""
        proceso = self._proceso_de(flow)

        # El destino filtra antes que el contenido. Un equipo genera miles de
        # peticiones por hora y casi ninguna va a una IA: escanearlas todas
        # gasta CPU en cada clic y llena el panel de hallazgos que a nadie le
        # importan, porque el dato nunca estuvo yendo a un modelo.
        if classification == "non_ai":
            preview = body[:PREVIEW_BYTES].decode("utf-8", errors="replace")
            tiene_forma = looks_like_ai_api(flow.request.path, preview)
            self.signals.observe_request(host, tiene_forma, preview)
            self._maybe_classify(host)
            if tiene_forma:
                classification = "ai_unknown"

        if classification != "non_ai":
            # Antes que el escaneo de fugas, y por separado: lo que se busca aca
            # no es un dato sensible sino una ORDEN para ir a buscarlo. En este
            # momento del ataque todavia no hay ningun secreto en el texto, asi
            # que ninguna de las otras reglas lo veria.
            if self._inyeccion_en_el_envio(flow, host, classification, body, proceso):
                return

            result = scan_payload(body, query, self.policy.company_terms)
            # Una credencial que viaja hacia su propio dueno no es una fuga: es
            # su uso normal. Claude Code manda su token a api.anthropic.com en
            # cada peticion, y bloquear eso solo logra que la herramienta no
            # pueda autenticarse.
            hallazgos = [
                f for f in result.findings if not exento(f.rule_id, host, flow.request.path)
            ]
            result = ScanResult(
                findings=hallazgos, truncated=result.truncated, views=result.views
            )
            # La decision vive en policy.decidir_sobre y no aca: es la misma que
            # tiene que medir el banco de pruebas. Cuando eran dos copias, el
            # banco reportaba ocho bloqueos falsos que el proxy nunca hacia.
            action = decidir_sobre(
                classification, result.findings, self.policy, proceso.nombre
            )
            worst = result.findings[0] if result.findings else None

            if action == "block_content" and worst is not None:
                evento = self._record(
                    host=host,
                    classification=classification,
                    finding=worst,
                    action="blocked",
                    payload_bytes=len(body),
                    truncated=result.truncated,
                    proceso=proceso.nombre,
                )
                # La leccion sale del cache en disco, siempre. Esto solo le pide
                # al backend la version generada para la PROXIMA vez: nadie la
                # espera y el bloqueo ya esta resuelto.
                if os.environ.get("AEGIS_BACKEND_DISABLED") != "1":
                    pedir_en_segundo_plano(
                        evento, os.environ.get("AEGIS_BACKEND", "http://127.0.0.1:8686")
                    )
                leccion = lesson_for(worst.rule_id)
                _deny(
                    flow,
                    blockpage.content_blocked(
                        host,
                        worst.rule_id,
                        worst.evidence,
                        leccion,
                        aprobada=classification == "ai_approved",
                    ),
                    f"Aegis bloqueo el envio: {leccion['title']}. "
                    f"{leccion['what_to_do']}",
                    {
                        "X-Aegis-Action": "block_content",
                        "X-Aegis-Rule": worst.rule_id,
                    },
                )
            else:
                if worst is not None:
                    self._record(
                        host=host,
                        classification=classification,
                        finding=worst,
                        action="warned" if action == "warn" else "allowed",
                        payload_bytes=len(body),
                        truncated=result.truncated,
                        proceso=proceso.nombre,
                    )

    def _registrar_uso(
        self, host: str, classification: Classification, proceso: str = ""
    ) -> None:
        """Un evento por dominio cada tanto, no uno por peticion.

        Una sola pestana de chat dispara decenas de peticiones por minuto: sin
        esta pausa el panel se vuelve ilegible y la cola, inutil.
        """

        ahora = time.time()
        with self._lock_uso:
            reciente = ahora - self._ultimo_uso.get(host, 0) < PAUSA_USO
            if not reciente:
                self._ultimo_uso[host] = ahora
        if not reciente:
            self._record(
                host=host,
                classification=classification,
                finding=None,
                action="allowed",
                payload_bytes=0,
                truncated=False,
                proceso=proceso,
            )

    def _record(
        self,
        *,
        host: str,
        classification: Classification,
        finding: Finding | None,
        action: str,
        payload_bytes: int,
        truncated: bool,
        proceso: str = "",
    ) -> dict:
        event = build_event(
            tenant_id=self.policy.tenant_id,
            user_id=self.user_id,
            area=self.area,
            host=host,
            classification=classification,
            process=proceso or DESCONOCIDO,
            finding=finding,
            action=action,
            payload_bytes=payload_bytes,
            truncated=truncated,
        )
        enqueue(event, self.queue)
        return event


# Aca NO va `addons = [Aegis()]`. mitmproxy carga el addon desde aegis_mitm.py,
# que existe justamente para eso; tenerlo tambien aca significa que importar
# este modulo (un test, una herramienta, un `python -c`) levanta un agente de
# verdad: lee la politica del HOME, se la pide al backend por la red y arranca
# el sensor de conexiones.
#
# Esto ya paso. La suite le escribia ~/.aegis/politica.json al desarrollador con
# lo que respondiera el backend que tuviera levantado, y los e2e despues leian
# ese archivo. Importar no puede tener efectos.
