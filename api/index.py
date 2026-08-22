"""Panel y base colaborativa de Aegis, como funcion serverless.

Sirve para que el equipo y el jurado vean el panel sin instalar nada. Reusa el
mismo codigo de metricas y de render que corre en el agente local: si el panel
desplegado miente, mienten tambien los 186 tests.

Dos advertencias que valen mas que cualquier comentario de implementacion:

1. Aca nunca llega contenido. Los eventos que sube el agente ya vienen
   redactados, y este servicio rechaza los que no lo esten. Es la misma frontera
   del ADR 0003, verificada de nuevo del lado que recibe.

2. El almacenamiento por defecto es efimero, porque en una funcion serverless no
   hay disco que sobreviva. Alcanza para probar y para mostrar; para que los
   eventos duren hay que conectar un almacen (ver AEGIS_KV_URL abajo).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agent"))
sys.path.insert(0, str(RAIZ / "backend"))

from aegis_agent.panel.demo_data import semana_simulada  # noqa: E402
from aegis_agent.panel.metrics import compute, repeat_offenders  # noqa: E402
from aegis_agent.panel.render import render  # noqa: E402

MAX_EVENTOS = 5000
CAMPOS_PROHIBIDOS = ("payload", "content", "text", "prompt", "body", "raw")
EVIDENCIA_MAX = 32

# Almacen opcional compatible con Upstash o Vercel KV. Sin esto el panel arranca
# con la semana de demostracion y guarda en memoria mientras la instancia viva.
KV_URL = os.environ.get("AEGIS_KV_URL") or os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("AEGIS_KV_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
KV_CLAVE = "aegis:eventos"

_memoria: list[dict] = []


def _kv_disponible() -> bool:
    return bool(KV_URL and KV_TOKEN)


def _kv(comando: list[str]) -> dict | None:
    peticion = urllib.request.Request(
        KV_URL.rstrip("/"),
        data=json.dumps(comando).encode(),
        headers={
            "Authorization": f"Bearer {KV_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(peticion, timeout=5) as respuesta:
            return json.loads(respuesta.read())
    except (urllib.error.URLError, OSError, ValueError):
        # Un almacen caido degrada el panel, nunca lo tumba.
        return None


def eventos() -> list[dict]:
    if _kv_disponible():
        respuesta = _kv(["LRANGE", KV_CLAVE, "0", str(MAX_EVENTOS)])
        crudos = (respuesta or {}).get("result") or []
        guardados = [json.loads(e) for e in crudos if e]
    else:
        guardados = list(_memoria)
    return guardados or semana_simulada()


def guardar(evento: dict) -> None:
    if _kv_disponible():
        _kv(["LPUSH", KV_CLAVE, json.dumps(evento, ensure_ascii=False)])
        _kv(["LTRIM", KV_CLAVE, "0", str(MAX_EVENTOS)])
    else:
        _memoria.insert(0, evento)
        del _memoria[MAX_EVENTOS:]


def lleva_contenido(evento: dict) -> bool:
    """La frontera del ADR 0003, revisada del lado que recibe.

    No alcanza con que el agente prometa no mandar contenido: el servicio que lo
    recibe tiene que poder rechazarlo, porque cualquiera puede escribir a este
    endpoint.
    """

    evidencia = (evento.get("detection") or {}).get("evidence", "")
    destino = evento.get("destination", {}).get("domain", "")
    return (
        any(campo in evento for campo in CAMPOS_PROHIBIDOS)
        or len(evidencia) > EVIDENCIA_MAX
        or "/" in destino
    )


def _ruta_pedida(path: str) -> str:
    """La ruta real que pidio el navegador.

    El rewrite de Vercel manda todo a /api/index, asi que la funcion nunca ve la
    ruta original: viene en el parametro que agrega el propio rewrite.
    """

    partes = urlsplit(path)
    # keep_blank_values importa: la raiz llega como ruta= vacio, y sin esto se
    # confundiria con "no vino el parametro" y la portada daria 404.
    consulta = parse_qs(partes.query, keep_blank_values=True)
    if "ruta" in consulta:
        ruta = "/" + consulta["ruta"][0].strip("/")
    else:
        ruta = partes.path
    return ruta.rstrip("/") or "/"


class handler(BaseHTTPRequestHandler):
    def _responder(self, estado: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, estado: int, datos: dict) -> None:
        self._responder(
            estado, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:  # noqa: N802
        ruta = _ruta_pedida(self.path)
        registrados = eventos()

        if ruta in ("/", "/panel"):
            metricas = compute(registrados)
            reincidencias = repeat_offenders(registrados)
            cuerpo = render(metricas, reincidencias, os.environ.get("AEGIS_TENANT", "acme"))
            self._responder(200, cuerpo.encode("utf-8"), "text/html; charset=utf-8")
        else:
            if ruta in ("/api/metrics", "/v1/metrics"):
                from dataclasses import asdict

                calculadas = compute(registrados)
                self._json(
                    200,
                    {
                        "metrics": {
                            **asdict(calculadas),
                            # block_rate es una propiedad, no un campo, asi que
                            # asdict no la trae y quien consuma la API la espera.
                            "block_rate": round(calculadas.block_rate, 1),
                        },
                        "repeats": repeat_offenders(registrados),
                        "almacen": "kv" if _kv_disponible() else "memoria",
                        "eventos": len(registrados),
                    },
                )
            else:
                if ruta == "/v1/health":
                    self._json(
                        200,
                        {
                            "ok": True,
                            "almacen": "kv" if _kv_disponible() else "memoria",
                            "eventos": len(registrados),
                        },
                    )
                else:
                    self._json(404, {"error": "ruta desconocida"})

    def do_POST(self) -> None:  # noqa: N802
        ruta = _ruta_pedida(self.path)
        largo = int(self.headers.get("Content-Length", "0") or 0)
        crudo = self.rfile.read(largo) if largo else b"{}"

        try:
            datos = json.loads(crudo or b"{}")
        except ValueError:
            datos = None

        if ruta not in ("/v1/events", "/api/events"):
            self._json(404, {"error": "ruta desconocida"})
        else:
            if not isinstance(datos, dict):
                self._json(400, {"error": "cuerpo invalido"})
            else:
                if lleva_contenido(datos):
                    self._json(422, {"error": "el evento contiene campos prohibidos"})
                else:
                    guardar(datos)
                    self._json(202, {"accepted": datos.get("event_id")})

    def log_message(self, *args) -> None:
        """Silencio: un log de accesos guardaria que dominios mira cada cliente."""
