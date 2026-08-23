from __future__ import annotations

import json
import os
import threading
import time

from mitmproxy import http

from .. import cert_siblings
from ..detect import model
from ..detect.payload import scan_payload, scan_preview
from ..detect.ruleset import ruleset_de
from ..domains import DomainClient
from ..detect.types import Finding
from ..events import DEFAULT_QUEUE, build_event, enqueue
from ..lessons import lesson_for
from ..policy import Classification, Policy, classify, decide, looks_like_ai_api
from ..policy_store import cargar as cargar_politica
from ..policy_store import refrescar_ahora
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
        )

    def _cortar_ruta_directa(self, punto) -> None:
        from ..install import firewall

        ruta = _ruta_del_proceso(punto.pid)
        if ruta:
            firewall.bloquear_programa(ruta, self.sensor.ips_conocidas())

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
                    )

    def response(self, flow: http.HTTPFlow) -> None:
        """Mira como responde el servidor, no solo que le pidieron.

        El streaming por eventos es la huella mas fiable de un modelo: casi
        ningun servicio normal responde asi y casi todos los chats con modelo si.
        """

        host = flow.request.pretty_host
        if classify(host, self.policy) == "non_ai" and flow.response is not None:
            self.signals.observe_response(
                host, flow.response.headers.get("Content-Type", "")
            )
            self._maybe_classify(host)

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
            if classification == "ai_unapproved":
                # Aunque se deje pasar, el uso de una herramienta no aprobada es
                # justamente lo que la empresa necesita ver en el panel.
                self._registrar_uso(host, classification)
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
        )
        _deny(
            flow,
            blockpage.destination_blocked(host, approved),
            f"Aegis bloqueo la conexion: {host} no es una herramienta de IA "
            f"aprobada por tu empresa. Usa {', '.join(approved)}.",
            {"X-Aegis-Action": "block_destination"},
        )

    def _inspect(
        self, flow: http.HTTPFlow, host: str, classification: Classification
    ) -> None:
        # Un snapshot por request: el hot-reload puede cambiar self.policy en
        # cualquier momento, y un mismo envio no puede escanearse con una
        # politica y decidirse con otra.
        politica = self.policy
        conjunto = ruleset_de(politica)
        # get_content decodifica gzip/brotli. Con raw_content, comprimir el body
        # alcanzaria para pasar cualquier secreto sin que ninguna regla lo vea.
        body = flow.request.get_content(strict=False) or b""
        query = str(flow.request.query) if flow.request.query else ""

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
            else:
                # "allow" es la salida de emergencia: reproduce el embudo de
                # siempre sin gastar ni el barrido barato. Es lo que le queda
                # a una empresa que decide que un destino sin clasificar nunca
                # merece la pena, ni para investigarlo.
                if politica.unknown_domain_action == "allow":
                    return
                # El request no tiene forma de llamada a un modelo, pero eso
                # no dice nada de lo que lleva adentro: un shadow AI interno
                # puede responder JSON plano sin streaming. Un barrido barato
                # (regex puro, sin contenedores) decide si vale la pena pagar
                # el escaneo completo; si no encuentra nada, el embudo termina
                # aca, igual que siempre.
                if not scan_preview(preview, ruleset=conjunto):
                    return
                # Salio un dato sensible hacia un destino que todavia no se
                # sabe si es una IA. Eso solo alcanza para investigar el
                # destino, no para tratarlo como una IA confirmada: la
                # decision de que hacer con el envio queda en manos de
                # unknown_domain_action, no de las reglas de siempre.
                self.signals.observe_sensitive_egress(host)
                self._maybe_classify(host)

        result = scan_payload(body, query, ruleset=conjunto)
        categories = {finding.category for finding in result.findings}
        action = decide(classification, categories, politica)
        worst = result.findings[0] if result.findings else None

        # Lo que vio el modelo no bloquea a ciegas: manda la categoria. Una
        # contrasena o un dato de empresa cortan igual que si los hubiera
        # visto T1; un dato personal suelto solo advierte, porque un
        # hallazgo probabilistico no puede frenar a nadie con la misma
        # autoridad que una llave de AWS con formato reconocido.
        del_modelo = worst is not None and worst.rule_id.startswith("modelo:")
        if del_modelo and action == "block_content":
            if politica.model_action == "warn":
                # Interruptor general: la empresa no confia en el modelo y
                # ningun hallazgo suyo bloquea, sin importar la categoria.
                action = "warn"
            else:
                etiqueta = model.etiqueta_de(worst.rule_id)
                autorizada = (
                    worst.category in politica.model_block_categories
                    and etiqueta in politica.model_block_labels
                )
                if not autorizada:
                    action = "warn"

        if action == "block_content" and worst is not None:
            self._record(
                host=host,
                classification=classification,
                finding=worst,
                action="blocked",
                payload_bytes=len(body),
                truncated=result.truncated,
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
                )

    def _registrar_uso(self, host: str, classification: Classification) -> None:
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
    ) -> None:
        event = build_event(
            tenant_id=self.policy.tenant_id,
            user_id=self.user_id,
            area=self.area,
            host=host,
            classification=classification,
            process="browser",
            finding=finding,
            action=action,
            payload_bytes=payload_bytes,
            truncated=truncated,
        )
        enqueue(event, self.queue)


addons = [Aegis()]
