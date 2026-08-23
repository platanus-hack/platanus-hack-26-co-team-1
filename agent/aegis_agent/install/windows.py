from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .. import entorno
from ..policy import PASSTHROUGH_DOMAINS

# Instalacion a nivel de usuario, nunca de maquina: la CA va al almacen personal
# y el proxy a HKCU. Eso se revierte sin permisos de administrador y sin dejar
# nada atras, que es lo minimo exigible a algo que se mete en medio de todo tu
# trafico.

MITM_CA_DIR = Path.home() / ".mitmproxy"
CA_CERT = MITM_CA_DIR / "mitmproxy-ca-cert.cer"
CA_PEM = MITM_CA_DIR / "mitmproxy-ca-cert.pem"

INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
CA_FRIENDLY_NAME = "mitmproxy"

# Estos nunca se interceptan: banca, salud, gobierno y lo que necesita el propio
# sistema para actualizarse. Es requisito de producto, no una optimizacion.
EXTRA_BYPASS = ("localhost", "127.0.0.1", "<local>")


@dataclass(frozen=True)
class Step:
    description: str
    detail: str


def proxy_bypass_list() -> str:
    dominios = [f"*.{d}" for d in sorted(PASSTHROUGH_DOMAINS)]
    return ";".join([*EXTRA_BYPASS, *dominios])


def env_vars(port: int) -> dict[str, str]:
    """Variables para las herramientas que ignoran el proxy del sistema.

    Todo lo que sea Node, Python, Go o Rust lee de aca y no del registro, y ahi
    viven justamente los CLIs de IA.
    """

    proxy = f"http://127.0.0.1:{port}"
    return {
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "NO_PROXY": ",".join(sorted(PASSTHROUGH_DOMAINS) + ["localhost", "127.0.0.1"]),
        "NODE_EXTRA_CA_CERTS": str(CA_PEM),
        "CODEX_CA_CERTIFICATE": str(CA_PEM),
        "SSL_CERT_FILE": str(CA_PEM),
        "REQUESTS_CA_BUNDLE": str(CA_PEM),
    }


def plan(port: int) -> list[Step]:
    """Lo que el instalador va a hacer, en orden y por escrito.

    Existe para poder mostrarlo antes de tocar nada: algo que se mete en el
    medio de todas tus conexiones tiene que poder explicarse en cinco lineas.
    """

    pasos = [
        Step("Generar la CA local de Aegis", str(CA_CERT)),
        Step("Confiar la CA en tu usuario (no en la maquina)", "certutil -addstore -user Root"),
        Step("Enrutar el navegador al proxy local", f"HKCU {INTERNET_SETTINGS} -> 127.0.0.1:{port}"),
        Step("Excluir banca, salud y gobierno", proxy_bypass_list()),
    ]
    pasos.extend(
        Step(f"Configurar {nombre} para las herramientas de linea de comandos", valor)
        for nombre, valor in env_vars(port).items()
    )
    return pasos


# -- generacion de la CA ----------------------------------------------------


def ensure_ca(mitmdump: str | None = None, timeout: int = 30) -> bool:
    """Crea la autoridad certificadora si no existe.

    Antes esto lanzaba `mitmdump --listen-port 0` y esperaba hasta treinta
    segundos a que el archivo apareciera en disco. Ahora la escribe `CertStore`
    directo, y eso importa por una razon concreta: adentro de un ejecutable
    empaquetado no hay ningun mitmdump que lanzar, y sin CA no hay producto.

    El parametro se conserva y se ignora para no romper a quien ya lo pasaba.
    """

    return entorno.generar_ca()


# -- registro de Windows ----------------------------------------------------


def _registry():
    import winreg

    return winreg


def _refresh_wininet() -> None:
    """Avisa a Windows que la configuracion cambio.

    Sin esto el navegador sigue con el proxy viejo hasta que se reinicia, y el
    usuario cree que el instalador no funciono.
    """

    import ctypes

    internet_option_settings_changed = 39
    internet_option_refresh = 37
    wininet = ctypes.windll.Wininet
    wininet.InternetSetOptionW(0, internet_option_settings_changed, 0, 0)
    wininet.InternetSetOptionW(0, internet_option_refresh, 0, 0)


def read_proxy_settings() -> dict:
    winreg = _registry()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS) as clave:
        def leer(nombre, defecto=None):
            try:
                return winreg.QueryValueEx(clave, nombre)[0]
            except FileNotFoundError:
                return defecto

        return {
            "enabled": bool(leer("ProxyEnable", 0)),
            "server": leer("ProxyServer", ""),
            "bypass": leer("ProxyOverride", ""),
        }


def write_proxy_settings(enabled: bool, server: str = "", bypass: str = "") -> None:
    winreg = _registry()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, INTERNET_SETTINGS, 0, winreg.KEY_SET_VALUE
    ) as clave:
        winreg.SetValueEx(clave, "ProxyEnable", 0, winreg.REG_DWORD, 1 if enabled else 0)
        if enabled:
            winreg.SetValueEx(clave, "ProxyServer", 0, winreg.REG_SZ, server)
            winreg.SetValueEx(clave, "ProxyOverride", 0, winreg.REG_SZ, bypass)
    _refresh_wininet()


# -- acciones ---------------------------------------------------------------


def ca_is_trusted() -> bool:
    resultado = subprocess.run(
        ["certutil", "-user", "-store", "Root"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return CA_FRIENDLY_NAME in resultado.stdout.lower()


def trust_ca() -> bool:
    resultado = subprocess.run(
        ["certutil", "-addstore", "-user", "Root", str(CA_CERT)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return resultado.returncode == 0


def untrust_ca() -> bool:
    resultado = subprocess.run(
        ["certutil", "-delstore", "-user", "Root", CA_FRIENDLY_NAME],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return resultado.returncode == 0


def set_env_vars(port: int) -> None:
    for nombre, valor in env_vars(port).items():
        subprocess.run(["setx", nombre, valor], capture_output=True, text=True)


def clear_env_vars() -> None:
    winreg = _registry()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as clave:
        for nombre in env_vars(0):
            try:
                winreg.DeleteValue(clave, nombre)
            except FileNotFoundError:
                pass


def puerto_escuchando(port: int) -> bool:
    """Si hay alguien atendiendo en el puerto del proxy AHORA.

    Es la diferencia entre "configurado" y "protegido", y hasta ahora el estado no
    la mostraba: se podia ver todo en verde con el proxy caido.
    """

    import socket

    with socket.socket() as sonda:
        sonda.settimeout(0.4)
        return sonda.connect_ex(("127.0.0.1", port)) == 0


def status(port: int) -> dict:
    proxy = read_proxy_settings()
    return {
        "ca_generada": CA_CERT.exists(),
        "ca_confiada": ca_is_trusted() if CA_CERT.exists() else False,
        "proxy_activo": proxy["enabled"],
        "proxy_servidor": proxy["server"],
        "apunta_a_aegis": proxy["server"] == f"127.0.0.1:{port}",
        "excluidos": proxy["bypass"],
        "arranca_solo": bool(arranque_registrado()),
        "escuchando": puerto_escuchando(port),
    }


# -- verificacion de cobertura ----------------------------------------------

# Destino inexistente a proposito. Verificar contra un servicio real significaria
# mandarle una credencial de juguete a un tercero justo cuando Aegis podria no
# estar funcionando, que es el unico momento en que eso llegaria a destino. El
# camino "/v1/chat/completions" alcanza para que el agente lo trate como IA.
URL_AUTOPRUEBA = "https://aegis-autoprueba.invalid/v1/chat/completions"

# Llave de ejemplo publicada por AWS en su documentacion: no abre nada.
SECRETO_DE_JUGUETE = "AKIAIOSFODNN7EXAMPLE"


def leer_variables_de_usuario() -> dict[str, str]:
    """Lo que quedo grabado de verdad, no lo que este proceso tiene en memoria."""

    winreg = _registry()
    valores: dict[str, str] = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as clave:
        for nombre in env_vars(0):
            try:
                valores[nombre] = winreg.QueryValueEx(clave, nombre)[0]
            except FileNotFoundError:
                pass
    return valores


def probar_en_vivo(port: int) -> tuple[bool, str]:
    """Manda un secreto de juguete por el proxy y mira si lo cortan.

    Es la unica fila de la tabla que no confia en la configuracion: la prueba.
    """

    import json
    import ssl
    import urllib.error
    import urllib.request

    contexto = ssl.create_default_context()
    if CA_PEM.exists():
        try:
            contexto.load_verify_locations(str(CA_PEM))
        except OSError:
            pass

    proxy = urllib.request.ProxyHandler(
        {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
    )
    abridor = urllib.request.build_opener(
        proxy, urllib.request.HTTPSHandler(context=contexto)
    )
    peticion = urllib.request.Request(
        URL_AUTOPRUEBA,
        data=json.dumps(
            {"messages": [{"role": "user", "content": f"mi llave es {SECRETO_DE_JUGUETE}"}]}
        ).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    try:
        with abridor.open(peticion, timeout=15) as respuesta:
            resultado = (False, f"el envio salio con codigo {respuesta.status}")
    except urllib.error.HTTPError as error:
        cortado = error.code == 403 and b"aegis_blocked" in error.read()
        if cortado:
            resultado = (True, "el secreto de prueba fue interceptado y cortado")
        else:
            resultado = (False, f"respondio {error.code}, pero no fue Aegis")
    except Exception as error:
        # Sin proxy escuchando no hay nada que verificar, y decirlo es mas util
        # que reportar una fila en rojo que suena a que Aegis esta roto.
        resultado = (False, f"no se pudo probar: {type(error).__name__}")
    return resultado


def verificar(port: int) -> list[tuple[str, bool, str]]:
    """Que camino queda cubierto y cual no, sobre esta maquina y no en teoria."""

    proxy = read_proxy_settings()
    ca_lista = CA_CERT.exists() and ca_is_trusted()
    sistema = proxy["enabled"] and proxy["server"] == f"127.0.0.1:{port}"

    variables = leer_variables_de_usuario()
    faltantes = [nombre for nombre in env_vars(port) if nombre not in variables]
    entorno = not faltantes and CA_PEM.exists()

    if ca_lista:
        motivo_ca = "CA propia confiada en tu usuario"
    else:
        motivo_ca = "falta confiar la CA: corre el instalador"

    if sistema:
        motivo_sistema = motivo_ca
    else:
        motivo_sistema = "el proxy del sistema no apunta a Aegis"

    if entorno:
        motivo_entorno = motivo_ca
    else:
        if faltantes:
            motivo_entorno = f"faltan variables: {', '.join(faltantes)}"
        else:
            motivo_entorno = f"falta el archivo de CA en {CA_PEM}"

    por_sistema = sistema and ca_lista
    por_entorno = entorno and ca_lista

    filas = [
        ("Navegador (Chrome, Edge)", por_sistema, motivo_sistema),
        ("App de escritorio (ChatGPT, Claude)", por_sistema, motivo_sistema),
        ("CLI de IA (Claude Code, Codex)", por_entorno, motivo_entorno),
        ("IDE con IA (Cursor, Copilot)", por_sistema and por_entorno, motivo_sistema if not por_sistema else motivo_entorno),
    ]

    cortado, detalle = probar_en_vivo(port)
    filas.append(("Prueba en vivo con un secreto", cortado, detalle))
    return filas


# -- arranque automatico -----------------------------------------------------
#
# Hasta ahora "instalar" configuraba la CA, el proxy del navegador y las
# variables de entorno, y no arrancaba nada. O sea que despues de instalar el
# navegador apuntaba a un puerto donde no habia nadie escuchando: la persona
# quedaba SIN internet hasta que alguien corriera el proxy a mano.
#
# Es la diferencia entre un proyecto y un producto, y es una falla del peor tipo
# --el usuario no puede saber que le falto un paso-- asi que el arranque va
# adentro de instalar.
#
# Se registra en HKCU\\...\\Run y no como servicio de Windows a proposito: un
# servicio necesita administrador y corre como otro usuario, y el proxy tiene que
# ver la sesion de la persona. Todo el instalador es reversible sin permisos de
# administrador (ADR 0001) y esto no lo cambia.
CLAVE_DE_ARRANQUE = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE_EN_ARRANQUE = "Aegis"


def comando_de_arranque(port: int) -> str:
    """La linea que Windows va a ejecutar al iniciar sesion."""

    partes = entorno.ejecutable_del_agente() + ["servicio"]
    return " ".join(f'"{parte}"' if " " in parte else parte for parte in partes)


def registrar_arranque(port: int) -> bool:
    winreg = _registry()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, CLAVE_DE_ARRANQUE, 0, winreg.KEY_SET_VALUE
        ) as clave:
            winreg.SetValueEx(
                clave, NOMBRE_EN_ARRANQUE, 0, winreg.REG_SZ, comando_de_arranque(port)
            )
        return True
    except OSError:
        return False


def quitar_arranque() -> bool:
    winreg = _registry()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, CLAVE_DE_ARRANQUE, 0, winreg.KEY_SET_VALUE
        ) as clave:
            winreg.DeleteValue(clave, NOMBRE_EN_ARRANQUE)
        return True
    except FileNotFoundError:
        # No estaba: desinstalar tiene que poder correrse dos veces sin quejarse.
        return True
    except OSError:
        return False


def arranque_registrado() -> str:
    winreg = _registry()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_DE_ARRANQUE) as clave:
            valor, _ = winreg.QueryValueEx(clave, NOMBRE_EN_ARRANQUE)
            return str(valor)
    except (FileNotFoundError, OSError, ValueError):
        # ValueError cubre un valor con una forma que no esperamos. Consultar el
        # estado tiene que ser SIEMPRE seguro: es lo primero que corre alguien
        # cuando algo anda mal, y reventar ahi lo deja sin la unica herramienta
        # de diagnostico que tiene.
        return ""


def install(port: int, mitmdump: str | None = None) -> list[str]:
    hechos = []
    if ensure_ca(mitmdump):
        hechos.append(f"CA generada en {CA_CERT}")
        if trust_ca():
            hechos.append("CA confiada en el almacen del usuario")
        else:
            # Windows exige confirmacion humana para instalar una CA raiz y no
            # hay forma de saltarla, ni deberia haberla. Se le da al usuario el
            # comando exacto en vez de dejarlo adivinando.
            hechos.append(
                "La CA necesita tu confirmacion. Corre esto y acepta el dialogo:\n"
                f'      certutil -addstore -user Root "{CA_CERT}"'
            )
    # OJO: aca NO se prende el proxy del navegador. Se prende en `enrutar()`, y
    # solo despues de confirmar que hay alguien escuchando en el puerto.
    #
    # Estaba al reves y esa es la causa de la peor falla que tuvo el producto:
    # instalar dejaba el navegador apuntando a 127.0.0.1 sin que nada estuviera
    # levantado, o sea a la persona SIN INTERNET, y sin ninguna pista de por que.
    # El orden no es un detalle de estilo: es el invariante.
    set_env_vars(port)
    hechos.append("Variables de entorno configuradas para los CLIs")
    if registrar_arranque(port):
        hechos.append("Aegis va a arrancar solo cuando inicies sesion")
    else:
        # Es el paso que convierte "configurado" en "protegido": si falla, hay que
        # decirlo fuerte, porque el proxy del navegador ya quedo apuntando a un
        # puerto donde no habria nadie escuchando.
        hechos.append(
            "NO se pudo registrar el arranque automatico. Aegis no va a levantarse "
            "solo, y el navegador esta apuntando al proxy: corre `aegis servicio` "
            "o desinstala."
        )
    return hechos


def enrutar(port: int) -> tuple[bool, str]:
    """Manda el trafico del navegador a Aegis. El ULTIMO paso, nunca antes.

    Se exigen las dos condiciones y ninguna es negociable:

      1. **Que haya alguien escuchando.** Prender el proxy sin eso deja a la
         persona sin internet, que es el unico estado en el que Aegis empeora el
         equipo. Ya paso.
      2. **Que la CA este confiada.** Sin eso cada sitio HTTPS muestra un aviso de
         certificado, y la persona queda peor que antes de instalar nada.
    """

    if not puerto_escuchando(port):
        return False, (
            f"NO se activo el proxy: no hay nada escuchando en el puerto {port}. "
            "Se prefiere quedarse sin proteccion antes que dejarte sin internet."
        )
    if not ca_is_trusted():
        return False, (
            "NO se activo el proxy: la CA no esta confiada y cada sitio HTTPS te "
            "mostraria una advertencia."
        )
    write_proxy_settings(True, f"127.0.0.1:{port}", proxy_bypass_list())
    return True, f"Proxy del navegador apuntando a 127.0.0.1:{port}"


def uninstall() -> list[str]:
    hechos = []
    write_proxy_settings(False)
    hechos.append("Proxy del navegador desactivado")
    if untrust_ca():
        hechos.append("CA retirada del almacen del usuario")
    clear_env_vars()
    hechos.append("Variables de entorno eliminadas")
    if quitar_arranque():
        hechos.append("Arranque automatico quitado")
    hechos.extend(_liberar_el_firewall())
    return hechos


def _liberar_el_firewall() -> list[str]:
    """Devuelve la red a los programas que Aegis le corto. NO es opcional.

    Cuando la capa D detecta un punto ciego y la politica dice "block", Aegis
    le pone una regla de firewall al programa para quitarle la ruta directa
    (ver proxy/addon.py). Esas reglas las pone Aegis y **las tiene que sacar
    Aegis**: hasta aca `uninstall` revertia el proxy, la CA, las variables y el
    arranque, y el firewall no lo tocaba nadie.

    El resultado era el peor estado posible del producto: alguien desinstala la
    herramienta de seguridad y su aplicacion sigue sin internet, sin ningun
    rastro de por que. Es la misma falla que ya tuvo el instalador al reves
    -dejar el navegador apuntando a un proxy muerto- y por el mismo motivo:
    lo que se toca del sistema se devuelve.

    Se nombran los programas liberados y no solo "listo": si alguien tuvo una
    app cortada durante dias, merece leer cual era.
    """

    from . import firewall

    hechos: list[str] = []
    puestas = firewall.reglas_puestas()
    if puestas:
        ok, _ = firewall.revertir()
        if ok:
            hechos.append(f"Firewall liberado ({len(puestas)} regla(s))")
            hechos.extend(f"  vuelve a tener red: {n}" for n in puestas)
        else:
            # Que falle no puede frenar el resto del desinstalador, pero
            # callarlo dejaria a alguien sin red y sin saberlo.
            hechos.append(
                "NO se pudieron quitar las reglas de firewall. Corre como "
                f'administrador: netsh advfirewall firewall delete rule group="{firewall.GRUPO}"'
            )
    return hechos


def main() -> int:
    """Se conserva para no romper `python -m aegis_agent.install.windows`.

    Antes esto hacia `sys.path.insert` y `from tests.e2e.harness import
    mitmdump_path`: el instalador de PRODUCCION importaba un modulo de tests. Los
    tests no se empaquetan, asi que en un ejecutable ese import reventaba --justo
    donde mas importaba que el instalador funcionara.

    El punto de entrada de verdad ahora es aegis_agent.cli, que es lo que se
    empaqueta.
    """

    from ..cli import main as cli

    return cli(sys.argv[1:] or ["status"])


if __name__ == "__main__":
    raise SystemExit(main())
