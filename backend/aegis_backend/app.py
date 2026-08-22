from __future__ import annotations

import json
import os
import threading
import time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .classifier import anthropic_model, classify
from .store import DomainStore, PolicyStore, SupabaseDomainStore, Verdict, store_from_env, vencido

DEFAULT_PORT = 8686

# La cola de clasificacion corre aparte del request que la disparo: el agente
# pregunta, recibe "todavia no se" al instante y sigue trabajando con su
# politica. Nadie espera a que un modelo se decida.
_pending: set[str] = set()
_pending_lock = threading.Lock()


class BackendHandler(BaseHTTPRequestHandler):
    def __init__(
        self,
        *args,
        store: DomainStore | SupabaseDomainStore,
        ask_model=None,
        policy_store: PolicyStore | None = None,
        **kwargs,
    ) -> None:
        self.store = store
        self.ask_model = ask_model
        self.policy_store = policy_store
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
        if self.path.startswith("/v1/domains/sync"):
            # Ruta especifica antes que el prefijo generico: "sync" no puede
            # caer en _domain() como si fuera el nombre de un dominio.
            self._domains_sync()
        else:
            if self.path.startswith("/v1/domains/"):
                self._domain(self.path[len("/v1/domains/") :])
            else:
                if self.path.startswith("/v1/policy/"):
                    self._policy_tenant(self.path[len("/v1/policy/") :])
                else:
                    if self.path.startswith("/v1/policy"):
                        self._send(200, _policy())
                    else:
                        if self.path.startswith("/v1/stats"):
                            self._send(200, {"domains": self.store.count()})
                        else:
                            self._send(404, {"error": "ruta desconocida"})

    def do_PUT(self) -> None:  # noqa: N802
        if self.path.startswith("/v1/policy/"):
            tenant = self.path[len("/v1/policy/") :].split("?")[0].strip("/")
            self._send(200, self.policy_store.put(tenant, self._body()))
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

    def _policy_tenant(self, tenant: str) -> None:
        tenant = tenant.split("?")[0].strip("/")
        self._send(200, self.policy_store.get(tenant))

    def _domain(self, domain: str) -> None:
        domain = domain.split("?")[0].strip("/").lower()
        verdict = self.store.get(domain)
        if verdict is not None:
            # El camino critico nunca se queda sin respuesta: un veredicto
            # vencido igual se manda, y la reclasificacion se encola aparte.
            # Un veredicto viejo siempre es mejor que ninguno.
            if vencido(verdict, time.time()):
                self._enqueue(domain)
            self._send(200, verdict.as_response())
        else:
            self._enqueue(domain)
            self._send(202, {"domain": domain, "classification": "pending"})

    def _domains_sync(self) -> None:
        """El delta que el agente baja para su cache local.

        La comparacion del camino critico (ver suffixes.py) nunca toca la
        base: el agente sincroniza de vez en cuando y compara en memoria. Sin
        `desde`, se manda todo -- lo mismo que un agente nuevo pediria en su
        primer arranque.
        """

        query = parse_qs(urlsplit(self.path).query)
        marca = query.get("desde", ["1970-01-01T00:00:00Z"])[0]
        ahora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        veredictos = [v.as_response() for v in self.store.desde(marca)]
        self._send(200, {"dominios": veredictos, "hasta": ahora})

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


def serve(
    store: DomainStore,
    port: int = DEFAULT_PORT,
    ask_model=None,
    policy_store: PolicyStore | None = None,
) -> ThreadingHTTPServer:
    handler = partial(
        BackendHandler,
        store=store,
        ask_model=ask_model,
        policy_store=policy_store or PolicyStore(Path("aegis-policies.json")),
    )
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main() -> None:
    ruta = Path(os.environ.get("AEGIS_DB", "aegis-domains.json"))
    ruta_politicas = Path(os.environ.get("AEGIS_POLICY_DB", "aegis-policies.json"))
    puerto = int(os.environ.get("AEGIS_BACKEND_PORT", DEFAULT_PORT))
    store = store_from_env(ruta)
    policy_store = PolicyStore(ruta_politicas)
    modelo = anthropic_model()
    servidor = serve(store, puerto, modelo, policy_store)
    origen = "con clasificador de modelo" if modelo else "solo con heuristica"
    base = ruta if isinstance(store, DomainStore) else "Supabase"
    print(f"Backend de Aegis en http://127.0.0.1:{puerto} ({origen}, base: {base})")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
