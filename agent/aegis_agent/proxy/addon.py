from __future__ import annotations

import os

from mitmproxy import http

from ..detect.payload import scan_payload
from ..detect.types import Finding
from ..events import DEFAULT_QUEUE, build_event, enqueue
from ..lessons import lesson_for
from ..policy import Classification, Policy, classify, decide, looks_like_ai_api
from . import blockpage

# Solo estos metodos llevan payload hacia afuera. Un GET a una IA aprobada no se
# inspecciona: no hay nada que inspeccionar y si el costo de hacerlo.
METHODS_WITH_PAYLOAD = frozenset({"POST", "PUT", "PATCH"})

_HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}

_WS_REDACTED = "[Aegis bloqueo este mensaje: contenia informacion sensible]"


class Aegis:
    def __init__(self) -> None:
        self.policy = Policy()
        self.user_id = os.environ.get("AEGIS_USER", "u_demo")
        self.area = os.environ.get("AEGIS_AREA", "marketing")
        self.queue = DEFAULT_QUEUE

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

    def _handle(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        classification = classify(host, self.policy)

        if classification == "ai_unapproved":
            self._block_destination(flow, host, classification)
        else:
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
        flow.response = http.Response.make(
            403,
            blockpage.destination_blocked(host, approved).encode("utf-8"),
            {**_HTML_HEADERS, "X-Aegis-Action": "block_destination"},
        )

    def _inspect(
        self, flow: http.HTTPFlow, host: str, classification: Classification
    ) -> None:
        # get_content decodifica gzip/brotli. Con raw_content, comprimir el body
        # alcanzaria para pasar cualquier secreto sin que ninguna regla lo vea.
        body = flow.request.get_content(strict=False) or b""
        query = str(flow.request.query) if flow.request.query else ""
        result = scan_payload(body, query)

        if classification == "non_ai":
            preview = body[:4000].decode("utf-8", errors="replace")
            if looks_like_ai_api(flow.request.path, preview):
                classification = "ai_unknown"

        if classification == "non_ai":
            action = "allow"
        else:
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
            flow.response = http.Response.make(
                403,
                blockpage.content_blocked(
                    host, worst.rule_id, worst.evidence, lesson_for(worst.rule_id)
                ).encode("utf-8"),
                {
                    **_HTML_HEADERS,
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
