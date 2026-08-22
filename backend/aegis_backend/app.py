from __future__ import annotations

import json
import os
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .classifier import anthropic_model, classify
from .store import DomainStore, Verdict

DEFAULT_PORT = 8686

# La cola de clasificacion corre aparte del request que la disparo: el agente
# pregunta, recibe "todavia no se" al instante y sigue trabajando con su
# politica. Nadie espera a que un modelo se decida.
_pending: set[str] = set()
_pending_lock = threading.Lock()


class BackendHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, store: DomainStore, ask_model=None, **kwargs) -> None:
        self.store = store
        self.ask_model = ask_model
        super().__init__(*args, **kwargs)

    # -- utilidades ---------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _body(self) -> dict:
        largo = int(self.headers.get("Content-Length", "0") or 0)
        if largo:
            datos = json.loads(self.rfile.read(largo) or b"{}")
        else:
            datos = {}
        return datos

    def log_message(self, *args) -> None:
        """Silencio: los logs de acceso guardarian que dominios mira cada cliente."""

    # -- rutas --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/v1/domains/"):
            self._domain(self.path[len("/v1/domains/") :])
        else:
            if self.path.startswith("/v1/policy"):
                self._send(200, _policy())
            else:
                if self.path.startswith("/v1/stats"):
                    self._send(200, {"domains": self.store.count()})
                else:
                    self._send(404, {"error": "ruta desconocida"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/v1/events"):
            evento = self._body()
            # El backend rechaza cualquier evento que traiga contenido: la unica
            # forma de garantizar la frontera es no confiar ni en el agente.
            if _carries_content(evento):
                self._send(422, {"error": "el evento contiene campos prohibidos"})
            else:
                self._send(202, {"accepted": evento.get("event_id")})
        else:
            if self.path.startswith("/v1/lessons"):
                self._send(200, _lesson(self._body()))
            else:
                self._send(404, {"error": "ruta desconocida"})

    def _domain(self, domain: str) -> None:
        domain = domain.split("?")[0].strip("/").lower()
        verdict = self.store.get(domain)
        if verdict is not None:
            self._send(200, verdict.as_response())
        else:
            self._enqueue(domain)
            self._send(202, {"domain": domain, "classification": "pending"})

    def _enqueue(self, domain: str) -> None:
        with _pending_lock:
            nuevo = domain not in _pending
            if nuevo:
                _pending.add(domain)
        if nuevo:
            threading.Thread(
                target=self._classify, args=(domain,), daemon=True
            ).start()

    def _classify(self, domain: str) -> None:
        try:
            self.store.put(classify(domain, self.ask_model))
        finally:
            with _pending_lock:
                _pending.discard(domain)


def _carries_content(evento: dict) -> bool:
    prohibidos = ("payload", "content", "text", "prompt", "body", "raw")
    evidencia = (evento.get("detection") or {}).get("evidence", "")
    destino = evento.get("destination", {}).get("domain", "")
    return (
        any(campo in evento for campo in prohibidos)
        or len(evidencia) > 32
        or "/" in destino
    )


def _policy() -> dict:
    return {
        "policy_version": 1,
        "unknown_domain_action": "warn",
        "approved_ai": ["claude.ai", "api.anthropic.com"],
        "rules": {"secret": "block", "internal_data": "block", "pii": "warn"},
    }


def _lesson(peticion: dict) -> dict:
    return {
        "event_id": peticion.get("event_id"),
        "title": "Revisa que estas compartiendo",
        "body": "El agente bloqueo el envio. Consulta la leccion en tu equipo.",
    }


def serve(store: DomainStore, port: int = DEFAULT_PORT, ask_model=None) -> ThreadingHTTPServer:
    handler = partial(BackendHandler, store=store, ask_model=ask_model)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main() -> None:
    ruta = Path(os.environ.get("AEGIS_DB", "aegis-domains.json"))
    puerto = int(os.environ.get("AEGIS_BACKEND_PORT", DEFAULT_PORT))
    store = DomainStore(ruta)
    modelo = anthropic_model()
    servidor = serve(store, puerto, modelo)
    origen = "con clasificador de modelo" if modelo else "solo con heuristica"
    print(f"Backend de Aegis en http://127.0.0.1:{puerto} ({origen}, base: {ruta})")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
