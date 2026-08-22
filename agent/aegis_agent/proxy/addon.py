from __future__ import annotations

import json
import os
import threading
import time

from mitmproxy import http

from ..detect.payload import scan_payload
from ..domains import DomainClient
from ..detect.types import Finding
from ..events import DEFAULT_QUEUE, build_event, enqueue
from ..lessons import lesson_for
from ..policy import Classification, Policy, classify, decide, looks_like_ai_api
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
        self.policy = Policy()
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

        if classification != "non_ai":
            result = scan_payload(body, query)
            categories = {finding.category for finding in result.findings}
            action = decide(classification, categories, self.policy)
            worst = result.findings[0] if result.findings else None

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
