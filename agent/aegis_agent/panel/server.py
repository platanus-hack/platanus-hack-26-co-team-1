"""El panel local: lo que Aegis vio, y el interruptor para prenderlo y apagarlo.

## Por que este panel escribe y el de la empresa no

El panel desplegado (web/app.py) es de solo lectura a proposito: muestra lo que
paso, no toca ningun equipo. Este corre en la maquina de la persona, junto al
agente, y por eso puede hacer lo unico que desde afuera seria impensable --
prender y apagar la interceptacion de SU equipo.

## El ataque que hay que impedir, porque es real

Un endpoint que apaga un DLP, escuchando en 127.0.0.1 y sin autenticar, lo puede
apretar **cualquier pagina que la persona tenga abierta en otra pestana**: un
formulario apuntado a http://127.0.0.1:8787/api/proteccion se manda solo, sin que
nadie lo vea, y el navegador lo entrega igual que si lo hubiera pedido el panel.
Apagar la herramienta de seguridad desde una web seria el peor agujero que este
producto podria tener.

Tres capas, y ninguna sobra:

1. **Una cabecera propia** (`X-Aegis-Token`). Es la que hace el trabajo pesado:
   una cabecera no estandar obliga al navegador a pedir permiso con un preflight
   antes de mandar nada desde otro origen, y el panel no contesta ese preflight.
   Un formulario HTML no puede poner cabeceras, asi que ese camino queda muerto.
2. **Un token por proceso.** Se genera al arrancar y solo esta escrito en la
   pagina que sirve este mismo panel. Una pagina de otro origen no puede leerlo
   -- se lo impide la politica de mismo origen del navegador.
3. **El `Origin` se revisa.** Si viene y no es este panel, se rechaza sin mirar
   nada mas.

Y se escucha solo en 127.0.0.1, igual que antes: un panel que apaga defensas
abierto a la red local seria un regalo para cualquiera en el mismo wifi.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import control
from .metrics import compute, load_events, repeat_offenders
from .render import render

DEFAULT_PORT = 8787
MAX_CUERPO = 4096


class PanelHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, queue: Path, tenant: str, token: str, **kwargs) -> None:
        self.queue = queue
        self.tenant = tenant
        self.token = token
        super().__init__(*args, **kwargs)

    # -- lectura ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802  (firma de BaseHTTPRequestHandler)
        if self.path.startswith("/api/estado"):
            self._json(200, control.estado())
        else:
            # Se relee la cola en cada request: son pocos kilobytes y evita
            # servir metricas viejas mientras el agente sigue registrando.
            events = load_events(self.queue)
            metrics = compute(events)
            repeats = repeat_offenders(events)

            if self.path.startswith("/api/metrics"):
                self._json(200, {"metrics": asdict(metrics), "repeats": repeats})
            else:
                cuerpo = render(
                    metrics, repeats, self.tenant, control.estado(), self.token
                ).encode("utf-8")
                self._responder(200, cuerpo, "text/html; charset=utf-8")

    # -- escritura ----------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        # El cuerpo se lee SIEMPRE, incluso para rechazar. Si el servidor
        # contesta sin vaciarlo, el cliente queda escribiendo en un socket que
        # ya se cerro y el request muere con un reset en vez de con el 403 que
        # explica lo que paso. Lo encontro el test del Origin ajeno: el ataque
        # se frenaba igual, pero la respuesta no llegaba nunca.
        crudo = self._leer_cuerpo()

        if self.path.rstrip("/") != "/api/proteccion":
            self._json(404, {"ok": False, "mensaje": "no existe"})
        elif not self._autorizado():
            # Deliberadamente parco: a quien no deberia estar preguntando no se
            # le explica que le falto.
            self._json(403, {"ok": False, "mensaje": "no autorizado"})
        else:
            self._cambiar_proteccion(crudo)

    def _autorizado(self) -> bool:
        """Las dos comprobaciones que impiden que otra pagina apriete el boton."""

        origen = self.headers.get("Origin", "")
        propio = f"http://{self.headers.get('Host', '')}"
        if origen and origen != propio:
            return False
        enviado = self.headers.get("X-Aegis-Token", "")
        return bool(self.token) and secrets.compare_digest(enviado, self.token)

    def _leer_cuerpo(self) -> bytes:
        try:
            largo = min(int(self.headers.get("Content-Length", 0)), MAX_CUERPO)
            return self.rfile.read(largo) if largo > 0 else b""
        except (ValueError, TypeError, OSError):
            return b""

    def _cambiar_proteccion(self, crudo: bytes) -> None:
        try:
            datos = json.loads(crudo or b"{}")
            accion = str(datos.get("accion", "alternar")).lower()
        except (ValueError, TypeError):
            accion = "alternar"

        operacion = {
            "prender": control.prender,
            "apagar": control.apagar,
            "alternar": control.alternar,
        }.get(accion, control.alternar)

        ok, mensaje = operacion()
        self._json(200, {"ok": ok, "mensaje": mensaje, "estado": control.estado()})

    # -- plomeria -----------------------------------------------------------

    def _json(self, codigo: int, datos: dict) -> None:
        self._responder(
            codigo,
            json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _responder(self, codigo: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        # Este panel no se embebe en ningun lado y no tiene por que poder
        # embeberse: sin esto, otra pagina podria ponerlo en un iframe invisible
        # y hacer que la persona apriete el boton sin verlo.
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *args) -> None:
        """Silencio: el panel no escribe nada sobre el trafico que observa."""


def serve(
    queue: Path, port: int = DEFAULT_PORT, tenant: str = "acme", token: str = ""
) -> ThreadingHTTPServer:
    """El servidor, con su token. Uno nuevo por proceso si no se pasa ninguno."""

    handler = partial(
        PanelHandler,
        queue=queue,
        tenant=tenant,
        token=token or secrets.token_urlsafe(24),
    )
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main() -> None:
    queue = Path(os.environ.get("AEGIS_QUEUE", "aegis-events.jsonl"))
    port = int(os.environ.get("AEGIS_PANEL_PORT", DEFAULT_PORT))
    server = serve(queue, port)
    print(f"Panel de Aegis en http://127.0.0.1:{port} (cola: {queue})")
    server.serve_forever()


if __name__ == "__main__":
    main()
