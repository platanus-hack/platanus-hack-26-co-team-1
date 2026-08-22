"""Panel y base colaborativa de Aegis, como servicio web.

Reusa el mismo codigo de metricas y de render que corre en el agente local: si
el panel desplegado miente, mienten tambien los tests que lo cubren.

Dos advertencias que valen mas que cualquier comentario de implementacion:

1. Aca nunca llega contenido. Los eventos que sube el agente ya vienen
   redactados, y este servicio rechaza los que no lo esten. Es la misma frontera
   del ADR 0003, verificada de nuevo del lado que recibe: no alcanza con que el
   agente prometa portarse bien.

2. El almacenamiento tiene tres niveles y el que corre depende del despliegue.
   Ver ALMACENAMIENTO mas abajo; es la razon por la que esto dejo de ser una
   funcion serverless.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agent"))
sys.path.insert(0, str(RAIZ / "backend"))

from aegis_agent.panel.demo_data import semana_simulada  # noqa: E402
from aegis_agent.panel.metrics import compute, repeat_offenders  # noqa: E402
from aegis_agent.panel.render import render  # noqa: E402

MAX_EVENTOS = 5000
CAMPOS_PROHIBIDOS = ("payload", "content", "text", "prompt", "body", "raw")
EVIDENCIA_MAX = 32
PUERTO_POR_DEFECTO = 10000

# ALMACENAMIENTO
#
# Tres niveles, de mas duradero a menos, y corre el primero disponible:
#
#   1. KV externo (Upstash o compatible), si hay AEGIS_KV_URL. Sobrevive a todo.
#   2. Disco, si AEGIS_DATA_DIR apunta a algo escribible. En Render eso es un
#      disco persistente montado, y sobrevive a los reinicios y a que el plan
#      gratuito apague la instancia por inactividad.
#   3. Memoria, mientras el proceso viva.
#
# El nivel 2 es lo que gano el servicio al mudarse: en una funcion serverless no
# habia disco que sobreviviera a la invocacion, asi que la unica persistencia
# posible era pagar un KV aparte.
KV_URL = os.environ.get("AEGIS_KV_URL") or os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("AEGIS_KV_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
KV_CLAVE = "aegis:eventos"

DATA_DIR = os.environ.get("AEGIS_DATA_DIR", "").strip()

_memoria: list[dict] = []


def _kv_disponible() -> bool:
    return bool(KV_URL and KV_TOKEN)


def _archivo() -> Path | None:
    """La cola en disco, o None si no hay un directorio utilizable.

    Se comprueba que se pueda escribir de verdad y no solo que la variable
    exista: un disco mal montado tiene que degradar a memoria, no tumbar el
    panel en el primer POST.
    """

    if not DATA_DIR:
        ruta = None
    else:
        carpeta = Path(DATA_DIR)
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            prueba = carpeta / ".escribible"
            prueba.write_text("ok", encoding="utf-8")
            prueba.unlink()
            ruta = carpeta / "eventos.jsonl"
        except OSError:
            ruta = None
    return ruta


ARCHIVO = _archivo()


def almacen() -> str:
    if _kv_disponible():
        nombre = "kv"
    else:
        nombre = "disco" if ARCHIVO else "memoria"
    return nombre


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
            resultado = json.loads(respuesta.read())
    except (urllib.error.URLError, OSError, ValueError):
        # Un almacen caido degrada el panel, nunca lo tumba.
        resultado = None
    return resultado


def _leer_disco() -> list[dict]:
    try:
        lineas = ARCHIVO.read_text(encoding="utf-8").splitlines()
    except OSError:
        lineas = []

    guardados = []
    for linea in lineas:
        limpia = linea.strip()
        if limpia:
            try:
                guardados.append(json.loads(limpia))
            except ValueError:
                # Una linea a medio escribir no invalida las demas.
                pass
    # El archivo se escribe en orden cronologico y el panel espera lo mas
    # reciente primero.
    guardados.reverse()
    return guardados[:MAX_EVENTOS]


def eventos() -> list[dict]:
    if _kv_disponible():
        respuesta = _kv(["LRANGE", KV_CLAVE, "0", str(MAX_EVENTOS)])
        crudos = (respuesta or {}).get("result") or []
        guardados = [json.loads(e) for e in crudos if e]
    else:
        guardados = _leer_disco() if ARCHIVO else list(_memoria)
    return guardados or semana_simulada()


def guardar(evento: dict) -> None:
    if _kv_disponible():
        _kv(["LPUSH", KV_CLAVE, json.dumps(evento, ensure_ascii=False)])
        _kv(["LTRIM", KV_CLAVE, "0", str(MAX_EVENTOS)])
    else:
        if ARCHIVO:
            linea = json.dumps(evento, ensure_ascii=False) + "\n"
            try:
                with ARCHIVO.open("a", encoding="utf-8") as destino:
                    destino.write(linea)
            except OSError:
                # Si el disco falla en caliente, el panel sigue sirviendo.
                _memoria.insert(0, evento)
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


# EL FRONT
#
# Este servicio sirve dos cosas por la misma URL: el API que consume el panel y
# el panel en si, que es la app Angular de frontend/. Van juntos a proposito.
# Separados hacen falta dos servicios, una URL para cada uno y CORS en el medio,
# y todo eso para que dos piezas del mismo producto se hablen.
#
# El panel en HTML que arma Python sigue existiendo y queda de respaldo: si no
# hay build del front (un checkout sin npm, un test, alguien levantando esto a
# mano) el servicio sigue mostrando las metricas en vez de una pagina de error.
DIST = RAIZ / "frontend" / "dist" / "aegis-ui" / "browser"

_TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webmanifest": "application/manifest+json",
}


def hay_front() -> bool:
    return (DIST / "index.html").is_file()


def _archivo_del_front(ruta: str) -> Path | None:
    """El archivo que corresponde a esa ruta, o None si no hay ninguno.

    Se comprueba que el resultado siga estando DENTRO de dist: sin eso, un
    pedido a /../../etc/passwd sirve cualquier archivo de la maquina. Es la
    trampa clasica de servir archivos, y este proceso es publico.
    """

    if not hay_front():
        return None

    destino = (DIST / ruta.lstrip("/")).resolve()
    try:
        destino.relative_to(DIST.resolve())
    except ValueError:
        return None
    return destino if destino.is_file() else None


def _ruta_pedida(path: str) -> str:
    """La ruta real que pidio el navegador.

    En Vercel esto tenia que deshacer un rewrite que borraba la ruta original y
    la reinyectaba como parametro. Aca el path llega entero, que es como
    deberia haber sido siempre.
    """

    return urlsplit(path).path.rstrip("/") or "/"


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 para que el proxy de Render reuse la conexion. Con 1.0 cada
    # request paga un handshake nuevo y el panel se siente lento sin motivo.
    protocol_version = "HTTP/1.1"

    def _responder(self, estado: int, cuerpo: bytes, tipo: str) -> None:
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, estado: int, datos: dict) -> None:
        self._responder(
            estado,
            json.dumps(datos, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def do_GET(self) -> None:  # noqa: N802  (firma de BaseHTTPRequestHandler)
        ruta = _ruta_pedida(self.path)
        registrados = eventos()

        if ruta == "/panel" or (ruta == "/" and not hay_front()):
            # El panel en HTML. Es la portada solo cuando no hay front
            # construido; con front, queda accesible a proposito en /panel para
            # poder ver las metricas crudas sin depender del build.
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
                        "almacen": almacen(),
                        "eventos": len(registrados),
                    },
                )
            else:
                if ruta == "/v1/health":
                    self._json(
                        200,
                        {
                            "ok": True,
                            "almacen": almacen(),
                            "eventos": len(registrados),
                        },
                    )
                else:
                    self._servir_el_front(ruta)

    def _servir_el_front(self, ruta: str) -> None:
        """Un archivo del build, o el index para que enrute el navegador.

        La segunda mitad es la que importa: el enrutado de la app es del lado
        del cliente, asi que /admin/politicas no existe como archivo. Sin
        devolver el index, entrar directo a esa direccion o recargar la pagina
        da 404, y es el unico bug de esto que nadie ve navegando y todos ven
        cuando comparten un enlace.
        """

        archivo = _archivo_del_front(ruta)
        if archivo is None and hay_front():
            archivo = DIST / "index.html"

        if archivo is None:
            self._json(404, {"error": "ruta desconocida"})
        else:
            tipo = _TIPOS.get(archivo.suffix, "application/octet-stream")
            self._responder(200, archivo.read_bytes(), tipo)

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


def main() -> None:
    # Render inyecta PORT y espera que el servicio escuche en 0.0.0.0: atado a
    # 127.0.0.1 el health check nunca lo alcanza y el despliegue se marca caido.
    puerto = int(os.environ.get("PORT", PUERTO_POR_DEFECTO))
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Handler)
    front = "con el front" if hay_front() else "sin front, sirviendo el panel HTML"
    print(f"Aegis en :{puerto} ({front}, almacen: {almacen()})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
