"""Panel y base colaborativa de Aegis, como servicio web.

Reusa el mismo codigo de metricas y de render que corre en el agente local: si
el panel desplegado miente, mienten tambien los tests que lo cubren.

Dos advertencias que valen mas que cualquier comentario de implementacion:

1. Aca nunca llega contenido. Los eventos que sube el agente ya vienen
   redactados, y este servicio rechaza los que no lo esten. Es la misma frontera
   del ADR 0003, verificada de nuevo del lado que recibe: no alcanza con que el
   agente prometa portarse bien.

2. El almacenamiento tiene cuatro niveles y el que corre depende del despliegue.
   Ver ALMACENAMIENTO mas abajo; es la razon por la que esto dejo de ser una
   funcion serverless.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agent"))
sys.path.insert(0, str(RAIZ / "backend"))

from aegis_agent.panel.demo_data import semana_simulada  # noqa: E402
from aegis_agent.panel.metrics import compute, repeat_offenders  # noqa: E402
from aegis_agent.panel.render import render  # noqa: E402
from aegis_backend import cuentas, directorio, enrolamiento, rutas, supabase  # noqa: E402
from aegis_backend.classifier import anthropic_model  # noqa: E402
from aegis_backend.store import DomainStore, PolicyStore  # noqa: E402

MAX_EVENTOS = 5000
CAMPOS_PROHIBIDOS = ("payload", "content", "text", "prompt", "body", "raw")
EVIDENCIA_MAX = 32
PUERTO_POR_DEFECTO = 10000

# ALMACENAMIENTO
#
# Cuatro niveles, de mas duradero a menos, y corre el primero disponible:
#
#   0. Supabase, si hay SUPABASE_URL y la clave. Es el unico que sobrevive a un
#      redespliegue del plan gratuito, y el unico que puede consultarse desde
#      afuera. Ver backend/aegis_backend/supabase.py.
#   1. KV externo (Upstash o compatible), si hay AEGIS_KV_URL.
#   2. Disco, si AEGIS_DATA_DIR apunta a algo escribible. En Render eso es un
#      disco persistente montado, y sobrevive a los reinicios y a que el plan
#      gratuito apague la instancia por inactividad.
#   3. Memoria, mientras el proceso viva.
#
# Los niveles de abajo no son solo el caso "sin configurar": son la red que
# atrapa al de arriba cuando se cae. Un evento que Supabase no acepto se escribe
# igual en disco o en memoria, porque perderlo seria perder justo el incidente
# que paso mientras el almacen estaba caido.
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
    if supabase.configurado():
        nombre = "supabase"
    else:
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


def _local() -> list[dict]:
    if _kv_disponible():
        respuesta = _kv(["LRANGE", KV_CLAVE, "0", str(MAX_EVENTOS)])
        crudos = (respuesta or {}).get("result") or []
        guardados = [json.loads(e) for e in crudos if e]
    else:
        guardados = _leer_disco() if ARCHIVO else list(_memoria)
    return guardados


def _guardar_local(evento: dict) -> None:
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


# El panel se refresca solo y hay tres widgets que piden lo mismo. Con el
# almacen en memoria eso era gratis; contra Supabase es una llamada de red por
# refresco, y el panel abierto en una pantalla de oficina lo llamaria todo el
# dia. Dos segundos de cache no cambian nada de lo que se ve y le sacan al
# almacen la parte aburrida del trabajo.
VENTANA_DE_CACHE = 2.0
_cache: dict[str, tuple[float, list[dict]]] = {}


def eventos(tenant: str | None = None) -> list[dict]:
    """Los eventos de una empresa, o todos si no se pide ninguna.

    El cache va por tenant y no en una sola variable: con una sola, la primera
    empresa que carga el panel deja sus eventos ahi y la siguiente los recibe
    durante dos segundos. Un cache compartido entre inquilinos es una fuga con
    fecha de vencimiento, no un cache.
    """

    global _cache

    guardados: list[dict] | None = None
    if supabase.configurado():
        clave = tenant or ""
        anterior = _cache.get(clave)
        vigente = anterior is not None and (time.time() - anterior[0]) < VENTANA_DE_CACHE
        if vigente:
            guardados = anterior[1]
        else:
            guardados = supabase.leer_eventos(MAX_EVENTOS, tenant)
            if guardados is not None:
                _cache[clave] = (time.time(), guardados)

    # None es "Supabase no contesto", que no es lo mismo que "no hay eventos":
    # en ese caso se cae al nivel de abajo en vez de dar el panel por vacio.
    if guardados is None:
        guardados = _local()
        if tenant:
            guardados = [e for e in guardados if e.get("tenant_id") == tenant]

    # La semana simulada es lo ultimo y solo cuando no hay NADA: sirve para
    # ensenar el producto, y taparia un almacen recien conectado que todavia no
    # recibio su primer evento.
    return guardados or semana_simulada()



# A donde manda el boton de descarga si nadie configuro otra cosa.
#
# Apunta al repo de la hackaton y no al personal por una razon concreta: el
# personal es PRIVADO, y un asset de release en un repo privado contesta 404 a
# quien no sea colaborador. O sea que el boton "descargar" funcionaba para
# nosotros y para nadie mas, que es la peor forma de que algo falle: no se nota
# probandolo.
DESCARGA_POR_DEFECTO = (
    "https://github.com/platanus-hack/platanus-hack-26-co-team-1/releases/latest"
)


def _url_publica(host: str) -> str:
    """A donde tiene que reportar un agente, deducido de por donde entro.

    Se saca del Host y no de una constante porque este mismo codigo corre en
    Render, en una maquina de desarrollo y en los tests, y una URL fija manda a
    los tres al lugar equivocado en dos de los casos. `AEGIS_URL_PUBLICA` la
    fija cuando hay un proxy adelante que cambia el Host.
    """

    fijada = os.environ.get("AEGIS_URL_PUBLICA", "").strip().rstrip("/")
    if fijada:
        return fijada
    limpio = (host or "127.0.0.1").strip()
    esquema = "http" if limpio.startswith(("127.0.0.1", "localhost")) else "https"
    return f"{esquema}://{limpio}"


def guardar(evento: dict) -> None:
    global _cache

    subido = supabase.guardar_evento(evento) if supabase.configurado() else False
    if subido:
        # Sin esto el evento existe en la base pero el panel no lo ve hasta que
        # venza la ventana, y en una demo dos segundos de nada son eternos.
        _cache = {}
    else:
        _guardar_local(evento)


# La frontera del ADR 0003 se revisa del lado que recibe, y ahora se revisa en un
# solo lugar: estaba escrita dos veces, aca y en el backend, con dos nombres. Una
# regla de seguridad copiada es una que en algun momento se corrige en un lado
# solo. Ver backend/aegis_backend/rutas.py.
lleva_contenido = rutas.lleva_contenido


# EL BACKEND COLABORATIVO
#
# Dominios, politicas y lecciones estaban escritos y no estaban desplegados:
# `render.yaml` levanta este archivo y nada mas, asi que en produccion /v1/policy
# y /v1/domains no existian y el agente le pedia su politica al aire. Corren aca
# por la misma razon por la que el front tampoco tiene servicio propio: son
# piezas del mismo producto y separarlas cuesta una URL mas y CORS en el medio.
#
# El JSON local es el cache; lo que sobrevive a un redespliegue esta en Supabase.
_BASE = Path(DATA_DIR) if DATA_DIR else RAIZ
DOMINIOS = DomainStore(_BASE / "aegis-domains.json")
POLITICAS = PolicyStore(_BASE / "aegis-policies.json")
MODELO = anthropic_model()
_LECCIONES: dict[tuple, dict] = {}


def _tenant_de(ruta: str, prefijo: str) -> str:
    return ruta[len(prefijo) :].split("?")[0].strip("/")


# QUIEN VE QUE
#
# El panel era publico y mostraba TODOS los eventos, de todas las empresas: el
# contrato tiene `tenant_id` desde el primer dia y ninguna consulta lo miraba.
# Para un producto cuyo pitch es "tus datos no salen de tu empresa", que el
# panel de una muestre el trafico de otra no es un detalle de permisos.
#
# La regla que lo sostiene: **el tenant sale del token y nunca del pedido.** Si
# viniera en la URL, cualquier cuenta leeria los datos de cualquier otra
# cambiando un parametro, y ningun login arreglaria eso.
def sembrar_la_cuenta_inicial() -> None:
    """La cuenta con la que se entra la primera vez.

    La llama `main()` y no el import. Importar este modulo tiene que poder no
    tocar nada de afuera: sembrar al importar significa que cualquier test que
    haga `import app` -o cualquier herramienta que lo inspeccione- escribe una
    cuenta en la base de verdad. Es el mismo error que costo veintitres tests
    rojos con `addons = [Aegis()]` (docs/ESTADO.md, seccion 5).
    """

    usuario, contrasena, tenant = cuentas.cuenta_inicial()
    if cuentas.sembrar_si_no_hay(usuario, contrasena, tenant):
        print(f"Cuenta inicial creada: {usuario} (empresa {tenant})", flush=True)


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

    def _sesion(self) -> dict | None:
        """La sesion del token, o None. El tenant sale de aca y de ningun lado mas."""

        return cuentas.del_encabezado(self.headers.get("Authorization"))

    def _cuerpo(self) -> dict | None:
        largo = int(self.headers.get("Content-Length", "0") or 0)
        try:
            datos = json.loads(self.rfile.read(largo) if largo else b"{}")
        except ValueError:
            datos = None
        return datos if isinstance(datos, dict) else None

    # EL ENRUTADO
    #
    # Una tabla y no una escalera de if/else. El servicio empezo con tres rutas
    # y hoy tiene doce; con la escalera, agregar la siguiente cuesta un nivel de
    # anidamiento mas y la ultima ya estaba a siete. La tabla se lee de una
    # ojeada y hace evidente cual pide sesion y cual no, que es la propiedad que
    # de verdad hay que poder auditar de un vistazo.
    #
    # `None` en la columna de sesion = ruta publica.

    def do_GET(self) -> None:  # noqa: N802  (firma de BaseHTTPRequestHandler)
        # Los eventos se leen dentro de cada rama y no una vez arriba: con el
        # almacen en memoria daba igual, pero contra Supabase esa linea era una
        # consulta por cada archivo del front -cada .js, cada fuente, cada
        # icono- para armar una respuesta que ni los mira.
        ruta = _ruta_pedida(self.path)

        exactas = {
            "/api/metrics": self._metricas,
            "/v1/metrics": self._metricas,
            "/v1/health": self._salud,
            "/v1/policy": self._politica_por_defecto,
            "/v1/stats": self._estadisticas,
            "/v1/colaboradores": self._listar_colaboradores,
            "/v1/inventario": self._listar_inventario,
            "/v1/tenant": self._leer_tenant,
            "/v1/enrolamiento": self._listar_codigos,
            "/descargar": self._descargar,
        }

        if ruta == "/panel" or (ruta == "/" and not hay_front()):
            self._panel_en_html()
        else:
            if ruta in exactas:
                exactas[ruta]()
            else:
                if ruta.startswith("/v1/domains/"):
                    self._json(
                        *rutas.veredicto(ruta[len("/v1/domains/") :], DOMINIOS, MODELO)
                    )
                else:
                    if ruta.startswith("/v1/policy/"):
                        self._leer_politica(ruta)
                    else:
                        self._servir_el_front(ruta)

    # -- lecturas -----------------------------------------------------------

    def _panel_en_html(self) -> None:
        """El panel que arma Python. Es la portada solo cuando no hay front.

        Con front construido queda accesible a proposito en /panel, para poder
        ver las metricas crudas sin depender de que el build haya salido bien.
        """

        registrados = eventos()
        cuerpo = render(
            compute(registrados),
            repeat_offenders(registrados),
            os.environ.get("AEGIS_TENANT", "acme"),
        )
        self._responder(200, cuerpo.encode("utf-8"), "text/html; charset=utf-8")

    def _metricas(self) -> None:
        from dataclasses import asdict

        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            # `sesion["tenant"]` y no un parametro del pedido: es lo unico que
            # impide que una empresa lea el panel de otra.
            registrados = eventos(sesion["tenant"])
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
                    "tenant": sesion["tenant"],
                },
            )

    def _salud(self) -> None:
        self._json(200, {"ok": True, "almacen": almacen(), "eventos": len(eventos())})

    def _politica_por_defecto(self) -> None:
        self._json(200, rutas.politica_por_defecto())

    def _estadisticas(self) -> None:
        self._json(200, {"domains": DOMINIOS.count()})

    def _leer_politica(self, ruta: str) -> None:
        """El agente pide su politica sin token, y esta bien.

        No tiene con quien loguearse, y la politica es la configuracion que el
        agente OBEDECE, no datos de nadie. Con sesion manda la sesion, y asi el
        panel no puede leer la de otra empresa.
        """

        sesion = self._sesion()
        pedido = _tenant_de(ruta, "/v1/policy/")
        self._json(200, POLITICAS.get(sesion["tenant"] if sesion else pedido))

    def _listar_colaboradores(self) -> None:
        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            tenant = sesion["tenant"]
            # Los intentos salen de los eventos y no de una columna: guardarlos
            # en la fila de la persona seria un contador que hay que mantener al
            # dia y que se desincroniza en el primer borrado.
            registrados = eventos(tenant)
            intentos = Counter(
                (e.get("actor") or {}).get("user_id", "") for e in registrados
            )
            gente = [
                {**fila, "intentos": intentos.get(fila["usuario"], 0)}
                for fila in directorio.colaboradores(tenant)
            ]
            self._json(200, {"colaboradores": gente, "tenant": tenant})

    def _listar_inventario(self) -> None:
        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            tenant = sesion["tenant"]
            # Antes de listar, mirar que hay corriendo de verdad: cada evento
            # dice con que herramienta se hizo el envio, asi que la shadow AI se
            # descubre sola en vez de esperar a que alguien la escriba.
            directorio.descubrir_desde_eventos(tenant, eventos(tenant))
            self._json(200, {"inventario": directorio.inventario(tenant)})

    def _leer_tenant(self) -> None:
        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            datos = directorio.tenant(sesion["tenant"])
            self._json(200, datos or {"tenant": sesion["tenant"], "areas": []})

    def _descargar(self) -> None:
        """El boton de descarga. Redirige, no sirve el archivo.

        El paquete pesa 109 MB y el disco de Render es efimero: servirlo desde
        aca significaria meterlo en el repositorio y volver a subirlo en cada
        deploy. Se redirige a donde de verdad vive -- un release de GitHub -- y
        `AEGIS_DESCARGA_URL` lo apunta a otro lado sin tocar codigo.

        Si nadie lo configuro se DICE, en vez de mandar a la persona a un 404
        que parece un error del producto.
        """

        destino = (
            os.environ.get("AEGIS_DESCARGA_URL", "").strip() or DESCARGA_POR_DEFECTO
        )
        if destino:
            self.send_response(302)
            self.send_header("Location", destino)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self._json(
                503,
                {
                    "error": "todavia no hay una version publicada para descargar",
                    "como": "definir AEGIS_DESCARGA_URL con el enlace al paquete",
                },
            )

    def _listar_codigos(self) -> None:
        """Los codigos de la empresa de quien pregunta. De ninguna otra."""

        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            self._json(200, {"codigos": enrolamiento.listar(sesion["tenant"])})

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

        if not isinstance(datos, dict):
            self._json(400, {"error": "cuerpo invalido"})
        else:
            if ruta == "/v1/login":
                self._entrar(datos)
            elif ruta in ("/v1/events", "/api/events"):
                self._recibir_evento(datos)
            elif ruta == "/v1/registro":
                self._registrar_empresa(datos)
            elif ruta == "/v1/enrolar":
                self._enrolar(datos)
            elif ruta == "/v1/enrolamiento":
                self._con_sesion(datos, self._crear_codigo)
            elif ruta == "/v1/lessons":
                self._json(*rutas.leccion(datos, MODELO, _LECCIONES))
            elif ruta == "/v1/colaboradores":
                self._con_sesion(datos, self._guardar_colaboradores)
            elif ruta == "/v1/inventario":
                self._con_sesion(datos, self._guardar_inventario)
            elif ruta == "/v1/tenant":
                self._con_sesion(datos, self._guardar_tenant)
            else:
                self._json(404, {"error": "ruta desconocida"})

    def _recibir_evento(self, datos: dict) -> None:
        """Un evento, del equipo que dice su token y de ningun otro.

        EL TENANT SALE DEL TOKEN, NUNCA DEL CUERPO. Es la misma regla que
        gobierna a las sesiones, y aca es lo unico que separa un panel de un
        buzon abierto: hasta este cambio cualquiera con la URL podia mandar un
        evento con el tenant_id que se le ocurriera -- inventar incidentes en el
        panel de una empresa y atribuirselos a una persona real. En un producto
        cuyo valor es el registro, un registro donde cualquiera escribe no vale
        nada.
        """

        tenant = enrolamiento.tenant_del_encabezado(
            self.headers.get("Authorization")
        )
        if tenant is None:
            self._json(401, {"error": "este equipo no esta enrolado"})
        elif lleva_contenido(datos):
            self._json(422, {"error": "el evento contiene campos prohibidos"})
        else:
            # Se pisa lo que haya dicho el cuerpo. No se compara ni se rechaza:
            # que un agente mande otro tenant no es un ataque que valga la pena
            # distinguir, y rechazarlo solo le ensena a quien prueba cual era el
            # correcto.
            guardar({**datos, "tenant_id": tenant})
            self._json(202, {"accepted": datos.get("event_id")})

    def _registrar_empresa(self, datos: dict) -> None:
        """Crea una empresa, su primer admin, y el codigo para su primer equipo.

        Las tres cosas juntas y no en tres pantallas: una empresa sin admin no
        se puede mirar y un admin sin codigo no tiene como sumar un equipo, asi
        que separarlas solo produce estados a medias que alguien tiene que
        recordar completar.

        No pide sesion -- es el unico endpoint que crea una -- asi que lo unico
        que lo protege es que el nombre de empresa no exista. Alcanza para el
        alta autoservicio; una instalacion seria pone esto detras de una
        invitacion.
        """

        empresa = str(datos.get("empresa", "")).strip().lower()
        usuario = str(datos.get("usuario", "")).strip().lower()
        contrasena = str(datos.get("password", ""))

        if not (empresa and usuario and len(contrasena) >= 8):
            self._json(
                400,
                {"error": "hace falta empresa, usuario y una contrasena de 8 o mas"},
            )
        elif cuentas.buscar(usuario) is not None:
            # No se dice si lo que existe es el usuario o la empresa: es la
            # misma discrecion del login.
            self._json(409, {"error": "ese usuario ya existe"})
        else:
            cuentas.guardar(usuario, contrasena, empresa, rol="admin")
            directorio.guardar_tenant({"tenant": empresa, "areas": []})
            self._json(
                200,
                {
                    "tenant": empresa,
                    "token": cuentas.emitir(usuario, empresa, "admin"),
                    "codigo": enrolamiento.crear(empresa)["codigo"],
                },
            )

    def _enrolar(self, datos: dict) -> None:
        """Canjea el codigo por el token de equipo y por a donde reportar.

        Es el unico endpoint que crea una credencial sin sesion, asi que
        devuelve lo minimo: a que empresa entro, con que token, y a que URL
        mandar los eventos. Nada del panel, nada de la politica.
        """

        canje = enrolamiento.canjear(str(datos.get("codigo", "")))
        if canje is None:
            # Un solo motivo, igual que en el login: distinguir "no existe" de
            # "vencio" le confirma a quien prueba codigos cuales existieron.
            self._json(400, {"error": "codigo invalido o vencido"})
        else:
            base = _url_publica(self.headers.get("Host", ""))
            self._json(
                200,
                {
                    "tenant": canje["tenant"],
                    "token": canje["token"],
                    "eventos_url": f"{base}/v1/events",
                    "backend_url": base,
                },
            )

    def _crear_codigo(self, tenant: str, datos: dict) -> None:
        """Un codigo nuevo para la empresa de quien lo pide.

        El tenant lo entrega `_con_sesion` desde el TOKEN y no del cuerpo, por
        el mismo motivo de siempre: si viniera del cuerpo, cualquier admin
        podria fabricar codigos para la empresa de otro.
        """

        self._json(200, enrolamiento.crear(tenant))


    def _entrar(self, datos: dict) -> None:
        """Login. Un solo motivo de rechazo, a proposito.

        No se distingue "ese usuario no existe" de "la contrasena no va": la
        diferencia le confirma a quien prueba cuales cuentas existen, que es la
        mitad del trabajo de entrar.
        """

        cuenta = cuentas.autenticar(
            str(datos.get("usuario", "")), str(datos.get("password", ""))
        )
        if cuenta is None:
            self._json(401, {"error": "usuario o contrasena incorrectos"})
        else:
            self._json(
                200,
                {
                    "token": cuentas.emitir(
                        cuenta["usuario"], cuenta["tenant"], cuenta.get("rol", "admin")
                    ),
                    "usuario": cuenta["usuario"],
                    "tenant": cuenta["tenant"],
                    "rol": cuenta.get("rol", "admin"),
                },
            )

    # -- escrituras ---------------------------------------------------------

    def _con_sesion(self, datos: dict | None, hacer) -> None:
        """Casi toda escritura es igual: pedir sesion, validar cuerpo, actuar.

        Escrito una vez para que agregar una ruta no sea otra oportunidad de
        olvidarse del 401. Lo que llega a `hacer` ya tiene tenant y cuerpo
        validados, y el tenant viene del token: nunca del pedido.

        El cuerpo se recibe ya parseado y no se lee aca: `rfile` es un socket y
        se consume una sola vez, asi que leerlo de nuevo devolveria vacio.
        """

        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            if datos is None:
                self._json(400, {"error": "cuerpo invalido"})
            else:
                hacer(sesion["tenant"], datos)

    def _guardar_colaboradores(self, tenant: str, datos: dict) -> None:
        """Uno o muchos por la misma ruta: el alta manual y el CSV son lo mismo.

        Las filas invalidas se descartan y no cancelan al resto. Subir un CSV de
        cincuenta personas y que falle entero porque a una le falta el usuario
        es peor que dar de alta cuarenta y nueve y decir cuantas faltaron.
        """

        pedidas = datos.get("colaboradores") or [datos]
        guardadas = directorio.guardar_colaboradores(tenant, pedidas)
        self._json(
            200,
            {
                "guardados": guardadas,
                "descartados": len(pedidas) - len(guardadas),
            },
        )

    def _guardar_inventario(self, tenant: str, datos: dict) -> None:
        fila = directorio.guardar_en_inventario(tenant, datos)
        if fila is None:
            self._json(400, {"error": "hace falta nombre y una clase conocida"})
        else:
            self._json(200, fila)

    def _guardar_tenant(self, tenant: str, datos: dict) -> None:
        # El tenant sale de la sesion aunque el cuerpo traiga otro: si no, quien
        # entra a una empresa podria renombrar la de al lado.
        self._json(200, directorio.guardar_tenant({**datos, "tenant": tenant}))

    def do_DELETE(self) -> None:  # noqa: N802
        ruta = _ruta_pedida(self.path)
        sesion = self._sesion()

        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            if ruta.startswith("/v1/colaboradores/"):
                usuario = _tenant_de(ruta, "/v1/colaboradores/")
                directorio.borrar_colaborador(sesion["tenant"], usuario)
                self._json(200, {"borrado": usuario})
            else:
                self._json(404, {"error": "ruta desconocida"})

    def do_PUT(self) -> None:  # noqa: N802
        """La politica que escribe el panel. Es el unico PUT del servicio.

        Sin esto, la pantalla de Politicas era un formulario que no salia de la
        memoria del navegador: se llenaba, se guardaba, y al recargar volvia a
        estar como antes.

        Escribir SI pide sesion, y sobre el tenant de la sesion: la politica
        incluye el diccionario de terminos de la empresa, asi que dejar que un
        pedido sin token elija sobre que empresa escribe seria dejar que
        cualquiera desarme las reglas de cualquiera.
        """

        ruta = _ruta_pedida(self.path)
        datos = self._cuerpo()

        if not ruta.startswith("/v1/policy/"):
            self._json(404, {"error": "ruta desconocida"})
        else:
            sesion = self._sesion()
            if sesion is None:
                self._json(401, {"error": "sesion requerida"})
            elif datos is None:
                self._json(400, {"error": "cuerpo invalido"})
            else:
                self._json(200, POLITICAS.put(sesion["tenant"], datos))

    def log_message(self, *args) -> None:
        """Silencio: un log de accesos guardaria que dominios mira cada cliente."""


def main() -> None:
    # Render inyecta PORT y espera que el servicio escuche en 0.0.0.0: atado a
    # 127.0.0.1 el health check nunca lo alcanza y el despliegue se marca caido.
    puerto = int(os.environ.get("PORT", PUERTO_POR_DEFECTO))
    sembrar_la_cuenta_inicial()
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), Handler)
    front = "con el front" if hay_front() else "sin front, sirviendo el panel HTML"
    print(f"Aegis en :{puerto} ({front}, almacen: {almacen()})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
