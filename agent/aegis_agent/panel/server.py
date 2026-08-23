from __future__ import annotations

import json
import os
from dataclasses import asdict
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .metrics import compute, load_events, repeat_offenders
from .render import render

DEFAULT_PORT = 8787


class PanelHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, queue: Path, tenant: str, **kwargs) -> None:
        self.queue = queue
        self.tenant = tenant
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802  (firma de BaseHTTPRequestHandler)
        # Se relee la cola en cada request: son pocos kilobytes y evita servir
        # metricas viejas mientras el agente sigue registrando.
        events = load_events(self.queue)
        metrics = compute(events)
        repeats = repeat_offenders(events)

        if self.path.startswith("/api/metrics"):
            payload = json.dumps(
                {"metrics": asdict(metrics), "repeats": repeats}, ensure_ascii=False
            ).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        else:
            payload = render(metrics, repeats, self.tenant).encode("utf-8")
            content_type = "text/html; charset=utf-8"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        """Silencio: el panel no escribe nada sobre el trafico que observa."""


def serve(queue: Path, port: int = DEFAULT_PORT, tenant: str = "acme") -> ThreadingHTTPServer:
    handler = partial(PanelHandler, queue=queue, tenant=tenant)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main() -> None:
    queue = Path(os.environ.get("AEGIS_QUEUE", "aegis-events.jsonl"))
    port = int(os.environ.get("AEGIS_PANEL_PORT", DEFAULT_PORT))
    server = serve(queue, port)
    print(f"Panel de Aegis en http://127.0.0.1:{port} (cola: {queue})")
    server.serve_forever()


if __name__ == "__main__":
    main()
