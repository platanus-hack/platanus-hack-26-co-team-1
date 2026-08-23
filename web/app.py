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
from urllib.parse import parse_qs, urlsplit

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agent"))
sys.path.insert(0, str(RAIZ / "backend"))

from aegis_agent.panel.demo_data import semana_simulada  # noqa: E402
from aegis_agent.panel.metrics import compute, filter_by_range, repeat_offenders  # noqa: E402
from aegis_agent.panel.render import render  # noqa: E402
from aegis_backend import (  # noqa: E402
    cuentas,
    directorio,
    enrolamiento,
    insights,
    intentos,
    rutas,
    supabase,
)
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


def son_de_ejemplo(eventos_mostrados: list[dict]) -> bool:
    """Si lo que se esta mostrando lo invento `semana_simulada`.

    Existe porque no decirlo es peligroso, y de una forma sutil: un panel lleno
    de actividad inventada se ve EXACTAMENTE igual que uno lleno de actividad
    real. Si el agente deja de reportar --el token vencio, la red se cayo, nadie
    conecto el equipo-- la empresa no ve un panel vacio que la haria preguntar:
    ve una semana normal y se queda tranquila.

    O sea que el generador que existe para ensenar el producto puede terminar
    tapando que el producto no esta funcionando. Se marca por el prefijo del
    `event_id`, que es lo unico que `semana_simulada` deja y nadie mas usa.
    """

    return bool(eventos_mostrados) and all(
        str(e.get("event_id", "")).startswith("demo-") for e in eventos_mostrados
    )



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
# Los insights piden un JSON con varios items -mas largo que un veredicto de
# dominio o una leccion-, asi que llevan su propio limite de tokens. Misma key,
# mismo `secretos.py` por debajo.
MODELO_INSIGHTS = anthropic_model(max_tokens=1800)
_LECCIONES: dict[tuple, dict] = {}
# Cache de insights por contenido (ver `insights.clave_de_cache`) y no por
# tenant: dos empresas con la misma foto agregada de la semana -algo que va a
# pasar seguido en una semana tranquila, donde la foto es "todo en cero"-
# reciben el mismo texto en vez de pagarlo dos veces.
_INSIGHTS: dict[str, dict] = {}


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

    def _de_donde_viene(self) -> str:
        """La IP a la que se le cuentan los intentos. Ver intentos.py."""

        return intentos.desde_donde(
            self.client_address[0] if self.client_address else "",
            self.headers.get("X-Forwarded-For"),
        )

    def _sin_turno(self) -> None:
        """El 429. Dice que hay que esperar y no cuantos intentos quedan: eso
        ultimo le mide el limite a quien esta probando."""

        self._json(429, {"error": "demasiados intentos, esperá unos minutos"})

    def _es_admin(self, sesion: dict | None) -> bool:
        return sesion is not None and cuentas.puede_escribir(sesion)

    def _puede_mirar(self, sesion: dict | None) -> bool:
        """Quien puede ver el panel de la empresa, aunque no pueda cambiarlo.

        MIRAR Y ESCRIBIR NO SON LA MISMA PUERTA, y este archivo llego a tener
        una sola. Las cuentas de colaborador y el rol `lector` nacieron en dos
        ramas distintas, y cada una resolvio "no es admin" a su manera: la de
        colaboradores cerro TODA lectura de empresa, que es correcto para un
        colaborador y deja afuera a un lector -- una cuenta que existe
        justamente para mirar y no tocar. Al juntarlas, `lector` se comia un 403
        en su unica funcion.

        Asi que son tres roles y no dos:

            admin        escribe y mira
            lector       mira, no escribe
            colaborador  ni una cosa ni la otra: solo lo suyo

        `/v1/mi-actividad` y `/v1/password` siguen siendo de cualquier cuenta
        sobre si misma, que es lo que le queda a un colaborador.
        """

        return sesion is not None and cuentas.rol_de(sesion) in (
            cuentas.ADMIN,
            cuentas.LECTOR,
        )

    def _rechazar_no_puede_mirar(self, sesion: dict | None) -> None:
        """El 401/403 de las lecturas de empresa. Ver _puede_mirar."""

        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            self._json(403, {"error": "esta cuenta no ve el panel de la empresa"})

    def _rechazar_no_admin(self, sesion: dict | None) -> None:
        """401 si no habia sesion, 403 si la habia pero no era de administracion.

        La distincion importa: a una cuenta de colaborador que entro bien y
        pidio una pantalla que no es la suya no se le puede decir "sesion
        requerida" -la tiene-, eso confundiria a cualquiera que este debugueando
        por que su cuenta valida no puede entrar a un lugar.

        Existe porque hasta aca cualquier cuenta autenticada -inclusive una de
        colaborador, que ahora existen de verdad- podia leer `/api/metrics` de
        toda la empresa o reescribir la politica: todo lo que llegaba hasta aca
        miraba que hubiera sesion, nunca que rol tuviera. `/v1/mi-actividad` y
        `/v1/password` son las excepciones a proposito: esas dos son de
        cualquier cuenta sobre si misma.
        """

        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            self._json(403, {"error": "esta cuenta no tiene permiso de administracion"})

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
            "/api/insights": self._insights,
            "/v1/insights": self._insights,
            "/v1/health": self._salud,
            "/v1/policy": self._politica_por_defecto,
            "/v1/stats": self._estadisticas,
            "/v1/colaboradores": self._listar_colaboradores,
            "/v1/inventario": self._listar_inventario,
            "/v1/tenant": self._leer_tenant,
            "/v1/enrolamiento": self._listar_codigos,
            "/v1/mi-actividad": self._mi_actividad,
            "/v1/usuarios": self._listar_usuarios,
            "/v1/colaborador": self._detalle_de_colaborador,
            "/descargar": self._descargar,
        }

        if ruta == "/panel" or (ruta == "/" and not hay_front()):
            self._panel_en_html()
        else:
            if ruta in exactas:
                exactas[ruta]()
            else:
                if ruta == "/v1/domains/sync":
                    # La ruta especifica va ANTES que el prefijo generico. Sin
                    # esto "sync" cae en veredicto() como si fuera el nombre de
                    # un dominio: el agente recibe {"domain":"sync"}, que no
                    # trae la clave "dominios", y su cache local nunca se
                    # actualiza. No falla ni deja rastro -- sincronizar() esta
                    # escrito para no romperse sin red -- asi que la base
                    # colaborativa deja de crecer en silencio.
                    self._sincronizar_dominios()
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

    def _registrados_del_rango(self, tenant: str) -> list[dict]:
        """Los eventos del tenant, acotados al `desde`/`hasta` del pedido.

        Comun a `/api/metrics` y `/api/insights`: los dos tienen que estar
        mirando la misma ventana, o el resumen pedagogico hablaria de una semana
        distinta a la que muestran los numeros de al lado.
        """

        parametros = parse_qs(urlsplit(self.path).query)
        desde = parametros.get("desde", [""])[0]
        hasta = parametros.get("hasta", [""])[0]
        return filter_by_range(eventos(tenant), desde, hasta)

    def _metricas(self) -> None:
        from dataclasses import asdict

        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
        else:
            # `sesion["tenant"]` y no un parametro del pedido: es lo unico que
            # impide que una empresa lea el panel de otra. `desde`/`hasta` si
            # vienen del pedido -son el rango que eligio quien mira el panel,
            # no un dato que decida a que empresa le pertenecen los eventos.
            registrados = self._registrados_del_rango(sesion["tenant"])
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
                    # Que el panel pueda decirlo. Ver `son_de_ejemplo`.
                    "de_ejemplo": son_de_ejemplo(registrados),
                },
            )

    def _insights(self) -> None:
        """El resumen pedagogico -riesgo, adopcion, estrategias- de la misma
        ventana que `/api/metrics`. Nunca ve una persona: ver `insights.py`."""

        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
        else:
            registrados = self._registrados_del_rango(sesion["tenant"])
            resultado = insights.generar(compute(registrados), MODELO_INSIGHTS, _INSIGHTS)
            self._json(200, resultado)

    def _salud(self) -> None:
        """Vive o no vive. Nada mas, y eso es a proposito.

        Render la consulta sin credencial para decidir si reinicia el servicio,
        asi que lo que conteste es publico. Devolvia ademas `len(eventos())`
        --sin tenant, o sea el total de TODAS las empresas-- y eso es un numero
        de negocio: quien la consulte cada hora dibuja la curva de uso de la
        plataforma sin tener cuenta. El estado del almacen se queda porque dice
        si el servicio esta sano, no cuanto lo usan.
        """

        self._json(200, {"ok": True, "almacen": almacen()})

    def _politica_por_defecto(self) -> None:
        self._json(200, rutas.politica_por_defecto())

    def _estadisticas(self) -> None:
        self._json(200, {"domains": DOMINIOS.count()})

    def _sincronizar_dominios(self) -> None:
        """El delta de la base colaborativa que el agente baja a su cache.

        Es lo que hace que un dominio investigado por UN equipo lo conozcan
        todos. La comparacion del camino critico nunca toca la red: el agente
        baja esto cada cinco minutos y compara en memoria.
        """

        desde = parse_qs(urlsplit(self.path).query).get("desde", [""])[0]
        self._json(*rutas.sincronizacion(DOMINIOS, desde))

    def _leer_politica(self, ruta: str) -> None:
        """La politica de una empresa: para su panel, o para sus agentes.

        ESTO NO PEDIA NADA, y el argumento para no pedirlo --"la politica es la
        configuracion que el agente OBEDECE, no datos de nadie"-- se quedo viejo
        dos veces.

        Primero porque dejo de ser cierto que no fueran datos de nadie: la
        politica lleva `company_terms`, el diccionario de nombres de proyecto,
        sistemas internos y archivos que la empresa carga a mano. `render.yaml`
        lo llama "la lista mas sensible del sistema" y la escritura de aca abajo
        ya la protegia por eso mismo. Con el nombre del tenant --que publica el
        registro y muestra el panel-- cualquiera se bajaba la lista de lo que la
        empresa considera secreto, de un producto que existe para que esa lista
        no salga. Era el producto al reves, igual que el panel publico que
        cuentas.py vino a cerrar.

        Y segundo porque dejo de ser cierto que el agente no tuviera con quien
        loguearse: desde el enrolamiento tiene token de equipo. Por eso valen
        las dos credenciales -- son los dos lectores legitimos-- y en las dos el
        tenant sale del token y nunca de la ruta.
        """

        sesion = self._sesion()
        if sesion is not None:
            tenant = sesion["tenant"]
        else:
            tenant = enrolamiento.tenant_del_encabezado(
                self.headers.get("Authorization")
            )

        if tenant is None:
            self._json(401, {"error": "hace falta una sesion o un equipo enrolado"})
        else:
            self._json(200, POLITICAS.get(tenant))

    def _listar_colaboradores(self) -> None:
        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
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

    def _mi_actividad(self) -> None:
        """Lo que UNA persona intento enviar, para que ella misma lo vea.

        No es `/api/metrics` con un filtro: ese endpoint es del admin y cuenta
        agregados de toda la empresa. Este es del colaborador y cuenta SUS
        propios intentos -por eso el usuario sale de la sesion y no de un
        parametro, igual que el tenant en todo lo demas-. Los campos que
        devuelve son los mismos que ya redacto el agente antes de subir el
        evento (ver ADR 0003): nada de esto es mas sensible de lo que la
        persona ya vio en su propia pantalla cuando el envio se corto.
        """

        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        else:
            propios = [
                e
                for e in eventos(sesion["tenant"])
                if (e.get("actor") or {}).get("user_id") == sesion["usuario"]
            ]
            propios.sort(key=lambda e: e.get("occurred_at", ""), reverse=True)
            entradas = [
                {
                    "occurred_at": e.get("occurred_at"),
                    "process": (e.get("destination") or {}).get("process"),
                    "domain": (e.get("destination") or {}).get("domain"),
                    "classification": (e.get("destination") or {}).get("classification"),
                    "action": e.get("action"),
                    "rule_id": (e.get("detection") or {}).get("rule_id"),
                    "category": (e.get("detection") or {}).get("category"),
                    "severity": (e.get("detection") or {}).get("severity"),
                }
                for e in propios[:100]
            ]
            self._json(200, {"actividad": entradas, "usuario": sesion["usuario"]})

    def _listar_inventario(self) -> None:
        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
        else:
            tenant = sesion["tenant"]
            # Antes de listar, mirar que hay corriendo de verdad: cada evento
            # dice con que herramienta se hizo el envio, asi que la shadow AI se
            # descubre sola en vez de esperar a que alguien la escriba.
            directorio.descubrir_desde_eventos(tenant, eventos(tenant))
            self._json(200, {"inventario": directorio.inventario(tenant)})

    def _leer_tenant(self) -> None:
        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
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

    def _detalle_de_colaborador(self) -> None:
        """Lo que hizo UNA persona, calculado sobre sus propios eventos.

        La pantalla que muestra esto era una maqueta: nombres inventados y una
        lista de intentos escrita a mano. Para un producto cuyo valor entero es
        el registro, una pantalla de registro que no viene del registro es lo
        peor que se puede mostrar -- y no hace falta que alguien la descubra
        para que haga dano: basta con que la empresa la crea y decida algo.

        Se reusa `compute` y el rango del pedido en vez de calcular aparte, para
        que los numeros de esta pantalla no puedan contradecir a los del panel
        general. Cuando eran dos calculos distintos, ese es exactamente el bug
        que aparece.
        """

        from dataclasses import asdict

        sesion = self._sesion()
        usuario = parse_qs(urlsplit(self.path).query).get("usuario", [""])[0].strip()

        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
        elif not usuario:
            self._json(400, {"error": "falta el usuario"})
        else:
            # El tenant sale de la SESION y el usuario del pedido: una empresa
            # puede mirar a los suyos y a nadie mas, aunque adivine un seudonimo.
            registrados = self._registrados_del_rango(sesion["tenant"])
            suyos = [
                e for e in registrados
                if (e.get("actor") or {}).get("user_id") == usuario
            ]
            ficha = next(
                (
                    c for c in directorio.colaboradores(sesion["tenant"])
                    if c.get("usuario") == usuario
                ),
                None,
            )
            calculadas = compute(suyos)
            self._json(
                200,
                {
                    "usuario": usuario,
                    "ficha": ficha,
                    "metrics": {
                        **asdict(calculadas),
                        "block_rate": round(calculadas.block_rate, 1),
                    },
                    "eventos": len(suyos),
                    # Lo ultimo que hizo, ya redactado: el contenido nunca
                    # estuvo en el evento, asi que aca tampoco puede estar.
                    "ultimos": [
                        {
                            # `occurred_at` y no `ts`: es el nombre del contrato
                            # de datos, el mismo que usa filter_by_range. Leer
                            # otro campo devuelve cadenas vacias y una lista que
                            # se ordena al azar, sin fallar.
                            "fecha": e.get("occurred_at", ""),
                            "destino": (e.get("destination") or {}).get("domain", ""),
                            "regla": (e.get("detection") or {}).get("rule_id", ""),
                            "accion": e.get("action", ""),
                        }
                        for e in sorted(
                            suyos,
                            key=lambda e: str(e.get("occurred_at", "")),
                            reverse=True,
                        )[:20]
                    ],
                },
            )

    def _listar_usuarios(self) -> None:
        """Quien puede entrar al panel de esta empresa, y con que permiso.

        Leer la lista NO pide ser admin: un lector tiene que poder ver a quien
        pedirle un cambio que el no puede hacer. Lo que pide admin es
        escribirla, y de eso se encarga `_con_sesion`.

        Pero tampoco alcanza con tener sesion, que es lo que pedia. Se escribio
        cuando los unicos roles eran admin y lector -- las dos son cuentas de la
        empresa mirando a la empresa -- y las de COLABORADOR llegaron por otra
        rama. Esta lista dice quien entra al panel y con que permiso: es el mapa
        de a quien conviene atacar, y no es asunto de un colaborador. Por eso
        `_puede_mirar` y no `_sesion`: la intencion de arriba se cumple igual
        --el lector sigue viendo la lista-- y el rol que no estaba previsto
        cuando se escribio queda afuera.
        """

        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
        else:
            self._json(
                200,
                {
                    "usuarios": cuentas.del_equipo(sesion["tenant"]),
                    "yo": sesion.get("usuario", ""),
                },
            )

    def _guardar_usuario(self, tenant: str, datos: dict) -> None:
        """Suma, cambia el rol o da de baja. Una ruta, tres verbos.

        Van juntas porque son la misma pantalla y el mismo permiso, y separarlas
        en tres rutas solo multiplica los lugares donde olvidarse del tenant.
        El tenant lo entrega `_con_sesion` desde el TOKEN: sin eso, el admin de
        una empresa administra el equipo de otra escribiendo su nombre.
        """

        usuario = str(datos.get("usuario", ""))
        rol = str(datos.get("rol", cuentas.LECTOR))

        if datos.get("baja"):
            if cuentas.sacar_del_equipo(tenant, usuario):
                self._json(200, {"baja": usuario})
            else:
                # Un solo motivo, igual que en el resto: distinguir "no existe"
                # de "es de otra empresa" confirma que ese usuario existe.
                self._json(
                    409, {"error": "no se puede dar de baja esa cuenta"}
                )
        elif datos.get("password"):
            nueva = cuentas.sumar_al_equipo(
                tenant, usuario, str(datos["password"]), rol
            )
            if nueva is None:
                self._json(
                    409,
                    {
                        "error": (
                            "revisá el usuario, el rol, y que la contraseña "
                            f"tenga {cuentas.LARGO_MINIMO_DE_CONTRASENA} "
                            "caracteres o más"
                        )
                    },
                )
            else:
                self._json(200, nueva)
        else:
            cambiada = cuentas.cambiar_rol(tenant, usuario, rol)
            if cambiada is None:
                self._json(409, {"error": "no se puede cambiar ese rol"})
            else:
                self._json(200, cambiada)

    def _listar_codigos(self) -> None:
        """Los codigos de la empresa de quien pregunta. De ninguna otra.

        Pedia sesion y nada mas, y eso alcanzaba cuando los unicos roles eran
        admin y lector: los dos son cuentas de la empresa mirando a la empresa.
        Con las cuentas de COLABORADOR --que existen desde que se junto la rama
        de auth-- ya no alcanza: un codigo de enrolamiento suma un equipo al
        panel, asi que la lista de codigos vivos es la lista de formas de meter
        una maquina adentro. No es una pantalla mas del panel.
        """

        sesion = self._sesion()
        if not self._puede_mirar(sesion):
            self._rechazar_no_puede_mirar(sesion)
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
            elif ruta == "/v1/usuarios":
                self._con_sesion(datos, self._guardar_usuario)
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

        # Aca se cuenta TODO intento y no solo los fallidos: en login y en
        # enrolar el abuso es acertar, en este el abuso es acertar MUCHAS veces
        # -- ocupar nombres de empresa hasta que el producto no sirva.
        marca = f"registro:{self._de_donde_viene()}"
        con_turno = intentos.permitido(marca)
        if con_turno:
            intentos.anotar(marca)

        if not con_turno:
            self._sin_turno()
        elif not (empresa and usuario and len(contrasena) >= 8):
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
                    "rol": cuentas.ADMIN,
                    "token": cuentas.emitir(usuario, empresa, cuentas.ADMIN),
                    "codigo": enrolamiento.crear(empresa)["codigo"],
                },
            )

    def _enrolar(self, datos: dict) -> None:
        """Canjea el codigo por el token de equipo y por a donde reportar.

        Es el unico endpoint que crea una credencial sin sesion, asi que
        devuelve lo minimo: a que empresa entro, con que token, y a que URL
        mandar los eventos. Nada del panel, nada de la politica.
        """

        # Solo por IP, y no por codigo: contar por codigo le daria a cualquiera
        # la forma de dejar sin canjear un codigo ajeno gastandole los intentos
        # antes de que lo use su dueno.
        marca = f"enrolar:{self._de_donde_viene()}"
        con_turno = intentos.permitido(marca)

        canje = None
        if con_turno:
            canje = enrolamiento.canjear(str(datos.get("codigo", "")))
            if canje is None:
                intentos.anotar(marca)

        if not con_turno:
            self._sin_turno()
        elif canje is None:
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

        usuario = str(datos.get("usuario", "")).strip().lower()
        # Por IP Y por usuario: ver intentos.py. Quien rota IPs choca con el
        # contador del usuario, y quien ataca a un usuario desde muchas IPs
        # choca con el de la IP.
        marcas = (f"login:{self._de_donde_viene()}", f"login:usuario:{usuario}")

        if not intentos.permitido(*marcas):
            self._sin_turno()
        else:
            cuenta = cuentas.autenticar(usuario, str(datos.get("password", "")))
            if cuenta is None:
                intentos.anotar(*marcas)
                self._json(401, {"error": "usuario o contrasena incorrectos"})
            else:
                # Entrar bien limpia la cuenta: si no, quien se equivoca cuatro
                # veces y acierta a la quinta arrastra el castigo cinco minutos.
                intentos.olvidar(*marcas)
                # `rol_de` y no `cuenta.get("rol", "admin")`: el default de esa
                # segunda forma es ABIERTO, y una fila vieja sin la columna
                # -o una cuenta creada antes de que el rol existiera- salia
                # administradora. Es la razon de ser de rol_de (ver cuentas.py).
                rol = cuentas.rol_de(cuenta)
                self._json(
                    200,
                    {
                        "token": cuentas.emitir(
                            cuenta["usuario"], cuenta["tenant"], rol
                        ),
                        "usuario": cuenta["usuario"],
                        "tenant": cuenta["tenant"],
                        "rol": rol,
                        # true solo para la cuenta que acaba de crear un admin
                        # con una temporal: el front frena en onboarding hasta
                        # que la persona elija la suya, en vez de dejarla seguir
                        # con la que le entregaron por otro canal.
                        "debe_cambiar_password": bool(cuenta.get("debe_cambiar")),
                    },
                )

    # -- escrituras ---------------------------------------------------------

    def _con_sesion(self, datos: dict | None, hacer) -> None:
        """Casi toda escritura es igual: pedir sesion, mirar el rol, actuar.

        Escrito una vez para que agregar una ruta no sea otra oportunidad de
        olvidarse del 401. Lo que llega a `hacer` ya tiene tenant y cuerpo
        validados, y el tenant viene del token: nunca del pedido.

        El rol se mira ACA y no en cada handler por el mismo motivo por el que
        se mira la sesion aca: es el unico lugar por el que pasan todas las
        escrituras, y el unico donde olvidarse cuesta una sola vez. Hasta este
        cambio el rol se emitia, se guardaba y se devolvia al frontend sin que
        nadie lo comparara nunca -- cualquier sesion valida podia emitir codigos
        de enrolamiento. Hoy no cambia nada porque todas las cuentas se crean
        admin; cambia el dia que exista la primera que no.

        El cuerpo se recibe ya parseado y no se lee aca: `rfile` es un socket y
        se consume una sola vez, asi que leerlo de nuevo devolveria vacio.
        """

        sesion = self._sesion()
        if not self._es_admin(sesion):
            self._rechazar_no_admin(sesion)
        else:
            if not cuentas.puede_escribir(sesion):
                self._json(403, {"error": "tu cuenta puede mirar, no cambiar"})
            elif datos is None:
                self._json(400, {"error": "cuerpo invalido"})
            else:
                hacer(sesion["tenant"], datos)

    def _guardar_colaboradores(self, tenant: str, datos: dict) -> None:
        """Uno o muchos por la misma ruta: el alta manual y el CSV son lo mismo.

        Las filas invalidas se descartan y no cancelan al resto. Subir un CSV de
        cincuenta personas y que falle entero porque a una le falta el usuario
        es peor que dar de alta cuarenta y nueve y decir cuantas faltaron.

        El directorio (`aegis_colaboradores`) y las cuentas con contrasena
        (`aegis_cuentas`) son dos tablas separadas -una es "quien es", la otra
        "quien puede entrar"-, pero el alta las junta: sin esto, "Colaboradores"
        agregaba gente al panel que no podia loguearse en ningun lado, y
        `/colaborador/login` no tenia con que cuentas comparar.
        """

        pedidas = datos.get("colaboradores") or [datos]
        guardadas = directorio.guardar_colaboradores(tenant, pedidas)
        for fila in guardadas:
            # Solo si TODAVIA no puede entrar: re-subir el mismo CSV para
            # corregir un cargo no puede resetear la contrasena que la
            # persona ya cambio.
            if cuentas.buscar(fila["usuario"]) is None:
                temporal = cuentas.generar_password_temporal()
                cuentas.guardar(fila["usuario"], temporal, tenant, rol="colaborador", debe_cambiar=True)
                fila["password_temporal"] = temporal
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

        if not self._es_admin(sesion):
            self._rechazar_no_admin(sesion)
        else:
            if ruta.startswith("/v1/colaboradores/"):
                usuario = _tenant_de(ruta, "/v1/colaboradores/")
                directorio.borrar_colaborador(sesion["tenant"], usuario)
                # Las dos tablas o ninguna: ver la nota en cuentas.borrar(). Se
                # mira el rol antes de tocar la cuenta -y no se borra si es
                # "admin"- por si el usuario coincidiera con el de otra cuenta
                # que no tiene nada que ver con este directorio.
                cuenta = cuentas.buscar(usuario)
                if cuenta is not None and cuenta.get("rol") == "colaborador":
                    cuentas.borrar(usuario)
                self._json(200, {"borrado": usuario})
            else:
                self._json(404, {"error": "ruta desconocida"})

    def do_PUT(self) -> None:  # noqa: N802
        """Las dos escrituras que no son POST: la politica y la contrasena propia.

        Escribir SI pide sesion en las dos. La politica sobre el tenant de la
        sesion -incluye el diccionario de terminos de la empresa, asi que dejar
        que un pedido sin token elija sobre que empresa escribe seria dejar que
        cualquiera desarme las reglas de cualquiera-. La contrasena sobre el
        USUARIO de la sesion: nadie cambia la de otro por esta via, ni siquiera
        un admin (para eso esta reemplazar a la persona en "Colaboradores").
        """

        ruta = _ruta_pedida(self.path)
        datos = self._cuerpo()

        if ruta.startswith("/v1/policy/"):
            sesion = self._sesion()
            if not self._es_admin(sesion):
                self._rechazar_no_admin(sesion)
            elif datos is None:
                self._json(400, {"error": "cuerpo invalido"})
            else:
                self._json(200, POLITICAS.put(sesion["tenant"], datos))
        else:
            if ruta == "/v1/password":
                self._cambiar_password(datos)
            else:
                self._json(404, {"error": "ruta desconocida"})

    def _cambiar_password(self, datos: dict | None) -> None:
        sesion = self._sesion()
        if sesion is None:
            self._json(401, {"error": "sesion requerida"})
        elif datos is None:
            self._json(400, {"error": "cuerpo invalido"})
        else:
            actual = str(datos.get("actual", ""))
            nueva = str(datos.get("nueva", ""))
            if len(nueva) < 8:
                # La misma regla que cualquier alta: menos de 8 no es una
                # contrasena, es una temporal disfrazada de definitiva.
                self._json(400, {"error": "la contraseña nueva necesita al menos 8 caracteres"})
            elif not cuentas.cambiar_password(sesion["usuario"], actual, nueva):
                self._json(401, {"error": "la contraseña actual no coincide"})
            else:
                self._json(200, {"ok": True})

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
