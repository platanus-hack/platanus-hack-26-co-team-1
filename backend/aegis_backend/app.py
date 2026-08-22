from __future__ import annotations

import json
import os
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import rutas
from .classifier import anthropic_model
from .store import DomainStore, PolicyStore

DEFAULT_PORT = 8686


class BackendHandler(BaseHTTPRequestHandler):
    def __init__(
        self,
        *args,
        store: DomainStore,
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
        if self.path.startswith("/v1/domains/"):
            self._domain(self.path[len("/v1/domains/") :])
        else:
            if self.path.startswith("/v1/policy/"):
                self._policy_tenant(self.path[len("/v1/policy/") :])
            else:
                if self.path.startswith("/v1/policy"):
                    self._send(200, rutas.politica_por_defecto())
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
            if rutas.lleva_contenido(evento):
                self._send(422, {"error": "el evento contiene campos prohibidos"})
            else:
                self._send(202, {"accepted": evento.get("event_id")})
        else:
            if self.path.startswith("/v1/lessons"):
                # Misma frontera que en /v1/events, y por la misma razon: el
                # endpoint es publico y no puede depender de que el agente se
                # porte bien. Una leccion no necesita el contenido.
                self._send(
                    *rutas.leccion(self._body(), self.ask_model, _CACHE_DE_LECCIONES)
                )
            else:
                self._send(404, {"error": "ruta desconocida"})

    def _policy_tenant(self, tenant: str) -> None:
        tenant = tenant.split("?")[0].strip("/")
        self._send(200, self.policy_store.get(tenant))

    def _domain(self, domain: str) -> None:
        self._send(*rutas.veredicto(domain, self.store, self.ask_model))


# La cache vive en el modulo y no en la peticion: dos empleados a los que se les
# corta la misma regla hacia el mismo tipo de destino merecen la misma leccion, y
# generarla dos veces es pagarla dos veces.
_CACHE_DE_LECCIONES: dict[tuple, dict] = {}


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
    store = DomainStore(ruta)
    policy_store = PolicyStore(ruta_politicas)
    modelo = anthropic_model()
    servidor = serve(store, puerto, modelo, policy_store)
    origen = "con clasificador de modelo" if modelo else "solo con heuristica"
    print(f"Backend de Aegis en http://127.0.0.1:{puerto} ({origen}, base: {ruta})")
    servidor.serve_forever()


if __name__ == "__main__":
    main()
