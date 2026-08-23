from __future__ import annotations

import json
import os
import threading
import time

from mitmproxy import http

from .. import cert_siblings, identidad
from ..detect import inyeccion, model
from ..detect.owners import exento
from ..detect.payload import (
    ScanResult,
    ordenar_hallazgos,
    scan_payload,
    scan_preview,
    texto_de_respuesta,
    texto_para_inyeccion,
)
from ..detect.ruleset import ruleset_de
from ..domains import DomainClient
from ..detect.types import EVIDENCE_MAX_LEN, Finding
from ..events import DEFAULT_QUEUE, build_event, enqueue
from ..lessons import lesson_for, pedir_en_segundo_plano
from ..policy import (
    Classification,
    classify,
    decidir_sobre,
    looks_like_ai_api,
)
from ..policy_store import cargar as cargar_politica
from ..policy_store import refrescar_ahora
from ..procesos import DESCONOCIDO, Proceso, del_puerto
from ..sensor import SensorDePuntosCiegos
from .. import adjuntos, aviso
from ..subidas import subida_hacia_una_ia
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

# Cuantas pasadas seguidas tiene que fallar el sensor antes de avisar. Tres y no
# una: un error aislado --la tabla de conexiones ocupada, un permiso que va y
# viene-- es ruido, y avisar de eso ensena a ignorar el aviso.
FALLAS_PARA_AVISAR = 3


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


def _deny(
    flow: http.HTTPFlow, html: str, mensaje: str, cabeceras: dict, app: str = ""
) -> None:
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
        # Aca se termina nuestro control: que la app pinte este mensaje o un
        # error generico lo decide ella, y no hay contrato que lo garantice.
        # Cuando se lo come, la persona ve que su mensaje fallo y no tiene una
        # sola pista de que fue Aegis ni de por que -- que es justo el escenario
        # que el producto existe para evitar, porque un bloqueo que no se
        # entiende no ensena nada y se siente como una falla de la herramienta.
        # Al navegador no se le avisa: ya recibio la pagina entera.
        #
        # Envuelto porque este es el camino del bloqueo: avisar es lo ultimo que
        # pasa y lo menos importante que pasa. Si el aviso falla, el envio tiene
        # que quedar cortado igual.
        try:
            aviso.avisar_bloqueo(mensaje, app, flow.request.pretty_host)
        except Exception:
            pass
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
        # Un dominio de IA confirmado se mira una sola vez por certificado: no
        # hace falta re-leer los SAN en cada request a la misma IA.
        self._hermanos_investigados: set[str] = set()
        self._lock_hermanos = threading.Lock()
        # El modelo tarda unos ocho segundos en cargar. Hacerlo en el primer
        # envio significa que la primera persona que abre un chat espera todo eso
        # con el request frenado, y llega a la conclusion correcta: que Aegis
        # rompe las cosas. Se carga aca, mientras nadie esta esperando.
        if model.habilitado():
            threading.Thread(target=model.cargar, daemon=True).start()

        self._url_backend = os.environ.get("AEGIS_BACKEND", "http://127.0.0.1:8686")
        # Cada cuanto se vuelve a pedir la politica. Un minuto alcanza: lo que
        # la web guarda tarda eso en aplicar, sin martillar el backend.
        try:
            self._intervalo_refresco = float(
                os.environ.get("AEGIS_REFRESCO_POLITICA", "60")
            )
        except ValueError:
            self._intervalo_refresco = 60.0

        if os.environ.get("AEGIS_BACKEND_DISABLED") != "1":
            # El refresco corre en bucle y aplica en caliente: la politica que
            # la web edita cambia el comportamiento sin reiniciar el agente.
            threading.Thread(target=self._refrescar_en_bucle, daemon=True).start()
            # La lista negra se sincroniza sola al arrancar y despues cada
            # tanto: nunca en el camino de una decision, que sigue siendo
            # 100% local (suffixes.py).
            threading.Thread(
                target=self.domains.sincronizar_en_segundo_plano, daemon=True
            ).start()

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
        seguidas = 0
        while True:
            try:
                for punto in self.sensor.revisar():
                    self._reportar_punto_ciego(punto)
                seguidas = 0
            except Exception as error:
                # El sensor es visibilidad, no proteccion: que falle no puede
                # llevarse puesto al proxy, que es lo que si esta protegiendo.
                # Por eso se traga la excepcion.
                #
                # Pero tragarsela SIEMPRE Y EN SILENCIO tiene su propio costo:
                # un sensor roto para siempre se ve igual que uno que no
                # encuentra nada, y la unica senal es que los puntos ciegos
                # dejan de aparecer -- que es justo lo que uno esperaria de una
                # red sana. Se avisa una sola vez, al cruzar el umbral, para no
                # convertir un bucle roto en un diluvio de mensajes.
                seguidas += 1
                if seguidas == FALLAS_PARA_AVISAR:
                    print(
                        f"[aegis] el sensor de puntos ciegos fallo "
                        f"{seguidas} veces seguidas: {error}"
                    )
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

    def _refrescar_politica(self) -> None:
        """Un tick del hot-reload: pedir, persistir y aplicar la politica.

        El swap es una asignacion de referencia (atomica en CPython) y solo
        pasa cuando la politica realmente cambio: el cache del ruleset es por
        identidad, y reemplazar el objeto sin necesidad recompilaria las
        regex en cada tick.
        """

        nueva = refrescar_ahora(self._url_backend, self.policy.tenant_id)
        if nueva is not None and nueva != self.policy:
            self.policy = nueva

    def _refrescar_en_bucle(self) -> None:
        while True:
            try:
                self._refrescar_politica()
            except Exception:
                # Un tick roto no puede matar el hilo: el proximo lo reintenta.
                pass
            time.sleep(self._intervalo_refresco)

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
            politica = self.policy
            classification = classify(host, politica)
            if classification not in ("passthrough", "non_ai"):
                result = scan_payload(
                    message.content if isinstance(message.content, bytes) else str(message.content).encode(),
                    ruleset=ruleset_de(politica),
                )
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

    def _descubrir_hermanos(self, flow: http.HTTPFlow, host: str) -> None:
        """Encola para investigar a los hermanos que el certificado revela.

        No los condena: los pone en la misma cola que cualquier otro dominio
        nuevo, para que Haiku decida. Se paga una sola vez por dominio de IA
        confirmado, no en cada request a la misma herramienta.
        """

        with self._lock_hermanos:
            ya_visto = host in self._hermanos_investigados
            if not ya_visto:
                self._hermanos_investigados.add(host)
        if not ya_visto:
            for hermano in self._hermanos_del_certificado(flow, host):
                self.domains.request_classification(hermano)

    def _hermanos_del_certificado(self, flow: http.HTTPFlow, host: str) -> list[str]:
        """Lee el CN y los SAN del certificado TLS de la conexion, sin lanzar.

        Un flow sin conexion TLS (HTTP plano, o un test que no simula el
        certificado) no tiene nada que leer aca, y eso no puede tumbar el
        request que si se esta protegiendo.
        """

        try:
            certificado = flow.server_conn.certificate_list[0]
        except (AttributeError, IndexError, TypeError):
            cn, altnames = None, []
        else:
            cn = getattr(certificado, "cn", None)
            try:
                altnames = [str(nombre.value) for nombre in certificado.altnames]
            except Exception:
                altnames = []
        return cert_siblings.hermanos(cn=cn, host=host, altnames=altnames)

    def _handle(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        classification = classify(host, self.policy)

        if classification == "non_ai":
            compartido = self.domains.cached(host)
            if compartido == "ai_unapproved":
                classification = "ai_unapproved"

        degradado_por_la_cuenta = False
        if classification == "ai_approved":
            # Aprobar la herramienta no es aprobar la cuenta. Va antes de
            # cualquier otra cosa porque puede cambiar la clasificacion, y todo
            # lo que sigue depende de ella.
            nueva = self._cuenta_de_la_empresa(flow, host, classification)
            degradado_por_la_cuenta = nueva != classification
            classification = nueva

        if classification in ("ai_approved", "ai_unapproved"):
            # El proxy ya termino el handshake TLS para llegar hasta aca: el
            # certificado esta en la mano y sus SAN casi siempre delatan a la
            # familia entera del servicio, sin una consulta de red mas.
            self._descubrir_hermanos(flow, host)

        corta_destino = (
            classification == "ai_unapproved"
            and self.policy.unapproved_ai_action == "block_destination"
        )
        if corta_destino:
            self._block_destination(flow, host, classification)
        else:
            if classification == "ai_unapproved" and not degradado_por_la_cuenta:
                # Aunque se deje pasar, el uso de una herramienta no aprobada es
                # justamente lo que la empresa necesita ver en el panel: con que
                # aplicacion la usan es la otra mitad del dato.
                #
                # Salvo cuando la degradacion vino de la cuenta: ese caso ya
                # dejo su propio evento, que ademas dice POR QUE. Registrar los
                # dos deja al panel con dos filas para una sola causa, y la
                # generica diciendo "allowed" al lado de la otra diciendo
                # "blocked". Dos evidencias que se contradicen es peor que
                # ninguna.
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
        # Un snapshot por request: el hot-reload puede cambiar politica en
        # cualquier momento, y un mismo envio no puede escanearse con una
        # politica y decidirse con otra.
        politica = self.policy
        conjunto = ruleset_de(politica)
        # get_content decodifica gzip/brotli. Con raw_content, comprimir el body
        # alcanzaria para pasar cualquier secreto sin que ninguna regla lo vea.
        body = flow.request.get_content(strict=False) or b""
        query = str(flow.request.query) if flow.request.query else ""
        proceso = self._proceso_de(flow)

        # El destino filtra antes que el contenido. Un equipo genera miles de
        # peticiones por hora y casi ninguna va a una IA: escanearlas todas
        # gasta CPU en cada clic y llena el panel de hallazgos que a nadie le
        # importan, porque el dato nunca estuvo yendo a un modelo.
        # Un destino sin clasificar al que le salio algo sensible NO pasa a ser
        # una IA: solo se vuelve digno de mirar. La diferencia importa, porque
        # que hacer con ese envio lo decide unknown_domain_action y no las
        # reglas de una IA confirmada.
        sospechoso = False

        # ¿Esto es un archivo yendose hacia una IA, y hacia cual?
        #
        # Se pregunta ACA --antes de mirar la clasificacion-- porque la
        # respuesta no depende de ella: sale de las cabeceras y del cuerpo. La
        # primera version preguntaba adentro de la rama `non_ai` y ahi solo
        # llegan los hosts de blobs que el catalogo no conoce, asi que la subida
        # mas comun de todas se la perdia: `files.oaiusercontent.com` SI esta en
        # el catalogo. Lo encontro un test de latencia.
        adjunto_hacia = subida_hacia_una_ia(
            flow.request.headers.get("Content-Type", ""),
            body,
            flow.request.headers.get("Origin", ""),
            flow.request.headers.get("Referer", ""),
            lambda candidato: classify(candidato, politica)
            not in ("non_ai", "passthrough"),
        )

        # La imagen se lee FUERA de este request. El archivo en el blob todavia
        # no es una fuga --nadie lo mira, ningun modelo lo leyo-- asi que la
        # proteccion no esta en frenar la subida sino en frenar el turno que le
        # pide al modelo que lo lea, y entre los dos hay una ventana real: la
        # persona todavia tiene que escribir y apretar enviar. Ver adjuntos.py.
        en_segundo_plano = False
        if politica.ocr_enabled and adjunto_hacia is not None:
            leidas = adjuntos.registrar(
                adjunto_hacia,
                body,
                body[:PREVIEW_BYTES].decode("utf-8", errors="replace"),
                lambda texto: scan_payload(
                    texto.encode("utf-8"),
                    terminos=politica.company_terms,
                    ruleset=conjunto,
                ).findings,
            )
            # Si la lectura se fue al fondo, este request no la paga de nuevo:
            # seria hacer el OCR dos veces y encima en el camino critico, que es
            # exactamente lo que se vino a sacar.
            en_segundo_plano = leidas > 0

        if classification == "non_ai":
            preview = body[:PREVIEW_BYTES].decode("utf-8", errors="replace")
            tiene_forma = looks_like_ai_api(flow.request.path, preview)
            self.signals.observe_request(host, tiene_forma, preview)
            self._maybe_classify(host)
            if tiene_forma:
                classification = "ai_unknown"
            else:
                # El adjunto se pregunta ANTES que el barrido barato, y el orden
                # no es casual: es una pregunta sobre el DESTINO, no sobre el
                # contenido. Los bytes de un archivo arrastrado a ChatGPT van a
                # files.oaiusercontent.com y no tienen forma de conversacion ni
                # texto donde una regex encuentre nada; con el barrido primero,
                # el adjunto se iba entero por el `return` de mas abajo.
                if adjunto_hacia is not None:
                    classification = "ai_unknown"
                else:
                    # "allow" es la salida de emergencia: reproduce el embudo de
                    # siempre sin gastar ni el barrido barato. Es lo que le queda
                    # a una empresa que decide que un destino sin clasificar
                    # nunca merece la pena, ni para investigarlo.
                    if politica.unknown_domain_action == "allow":
                        return
                    # El request no tiene forma de llamada a un modelo, pero eso
                    # no dice nada de lo que lleva adentro: un shadow AI interno
                    # puede responder JSON plano sin streaming. Un barrido barato
                    # (regex puro, sin contenedores) decide si vale la pena pagar
                    # el escaneo completo; si no encuentra nada, el embudo
                    # termina aca, igual que siempre.
                    if not scan_preview(preview):
                        return
                    self.signals.observe_sensitive_egress(host)
                    self._maybe_classify(host)
                    sospechoso = True

        if classification != "non_ai" or sospechoso:
            # Antes que el escaneo de fugas, y por separado: lo que se busca aca
            # no es un dato sensible sino una ORDEN para ir a buscarlo. En este
            # momento del ataque todavia no hay ningun secreto en el texto, asi
            # que ninguna de las otras reglas lo veria.
            if self._inyeccion_en_el_envio(flow, host, classification, body, proceso):
                return

            # Las reglas COMPILADAS de la politica y no las de fabrica: es lo
            # que hace que apagar una regla o agregar una regex propia cambie
            # algo. El compilado se cachea por identidad del objeto Policy, asi
            # que el hot-reload recompila una vez y no en cada request.
            # Tres estados, no dos (ver scan_payload): si la lectura ya se
            # fue al fondo se APAGA aunque el entorno la pida, si la politica
            # la pide se PRENDE, y si nadie dice nada se deja decidir a
            # `AEGIS_OCR`, que es el interruptor de siempre.
            if en_segundo_plano:
                mirar_imagenes = False
            else:
                mirar_imagenes = True if politica.ocr_enabled else None

            result = scan_payload(
                body,
                query,
                politica.company_terms,
                conjunto,
                mirar_imagenes,
            )
            # Lo que se subio antes a este mismo destino y se leyo mientras la
            # persona escribia. Se cobra ACA --en el turno, no en la subida--
            # porque es este request el que convierte el archivo en una fuga.
            if politica.ocr_enabled and not en_segundo_plano:
                de_adjuntos, sin_terminar = adjuntos.cobrar(host)
                if de_adjuntos or sin_terminar:
                    # Reordenado y no concatenado: `worst` es findings[0] y el
                    # hallazgo de la imagen puede ser peor que el del texto.
                    # Pegarlo al final lo dejaria fuera de la decision.
                    juntos = ordenar_hallazgos(result.findings + de_adjuntos)
                    result = ScanResult(
                        findings=juntos,
                        truncated=result.truncated or sin_terminar,
                        views=result.views,
                    )
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
                classification,
                result.findings,
                politica,
                proceso.nombre,
                self.user_id,
                self.area,
                host,
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

    def _cuenta_de_la_empresa(
        self, flow: http.HTTPFlow, host: str, classification: Classification
    ) -> Classification:
        """Degrada una herramienta aprobada usada con una cuenta que no es la de la empresa.

        La degradacion es a `ai_unapproved` y no a un estado nuevo, y eso es
        deliberado: la empresa ya decidio que hacer con una IA no aprobada
        (`unapproved_ai_action`), y esa decision vale igual acá. Un camino
        propio significaria dos lugares donde ajustar la misma politica.

        Cuando la accion es "warn" el envio sigue su curso exactamente como
        antes y lo unico que cambia es que el panel lo ve. Es el default a
        proposito: la primera pregunta que tiene una empresa no es a quien
        cortar sino cuanta gente esta entrando con su cuenta personal.
        """

        ajena = identidad.es_ajena(
            flow.request.headers,
            flow.request.path,
            self.policy.corporate_accounts,
        )
        corta = self.policy.foreign_account_action == "block"
        resultado = classification
        if ajena is not None:
            # Se decide ANTES de registrar. El evento tiene que decir lo que de
            # verdad paso: grabarlo como "aprobado" y degradar despues deja la
            # evidencia describiendo un mundo que no ocurrio.
            resultado = "ai_unapproved" if corta else classification
            self._registrar_uso(
                host,
                resultado,
                self._proceso_de(flow).nombre,
                # La identidad completa es la que compara la politica; esto es
                # solo lo que se muestra. Un uuid recortado a 32 sigue siendo
                # reconocible y el contrato no admite mas (ver detect/types.py).
                finding=Finding(
                    rule_id="cuenta_ajena",
                    category="policy",
                    severity="high",
                    confidence=1.0,
                    evidence=ajena[:EVIDENCE_MAX_LEN],
                    start=0,
                    end=0,
                ),
                accion="blocked" if corta else "warned",
                # Clave propia para que este evento no se coma la pausa del uso
                # normal del mismo dominio: son dos cosas distintas que el panel
                # necesita ver por separado.
                clave=f"cuenta:{host}",
            )
        return resultado

    def _registrar_uso(
        self,
        host: str,
        classification: Classification,
        proceso: str = "",
        finding: Finding | None = None,
        accion: str = "allowed",
        clave: str = "",
    ) -> None:
        """Un evento por dominio cada tanto, no uno por peticion.

        Una sola pestana de chat dispara decenas de peticiones por minuto: sin
        esta pausa el panel se vuelve ilegible y la cola, inutil.
        """

        ahora = time.time()
        llave = clave or host
        with self._lock_uso:
            reciente = ahora - self._ultimo_uso.get(llave, 0) < PAUSA_USO
            if not reciente:
                self._ultimo_uso[llave] = ahora
        if not reciente:
            self._record(
                host=host,
                classification=classification,
                finding=finding,
                action=accion,
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
