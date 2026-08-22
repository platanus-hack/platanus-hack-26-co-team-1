from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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


def ensure_ca(mitmdump: str, timeout: int = 30) -> bool:
    """Arranca mitmdump una vez, solo para que escriba su CA, y lo cierra."""

    if CA_CERT.exists():
        listo = True
    else:
        proceso = subprocess.Popen(
            [mitmdump, "--listen-port", "0", "--quiet"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            import time

            limite = time.time() + timeout
            while time.time() < limite and not CA_CERT.exists():
                time.sleep(0.2)
        finally:
            proceso.terminate()
            proceso.wait(timeout=10)
        listo = CA_CERT.exists()
    return listo


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


def status(port: int) -> dict:
    proxy = read_proxy_settings()
    return {
        "ca_generada": CA_CERT.exists(),
        "ca_confiada": ca_is_trusted() if CA_CERT.exists() else False,
        "proxy_activo": proxy["enabled"],
        "proxy_servidor": proxy["server"],
        "apunta_a_aegis": proxy["server"] == f"127.0.0.1:{port}",
        "excluidos": proxy["bypass"],
    }


def install(port: int, mitmdump: str) -> list[str]:
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
    # El proxy del navegador solo se activa si la CA quedo confiada. Sin eso,
    # cada sitio HTTPS mostraria un aviso de certificado y el usuario quedaria
    # peor que antes de instalar nada.
    if ca_is_trusted():
        write_proxy_settings(True, f"127.0.0.1:{port}", proxy_bypass_list())
        hechos.append(f"Proxy del navegador apuntando a 127.0.0.1:{port}")
    else:
        hechos.append("Proxy del navegador sin activar hasta que la CA este confiada")
    set_env_vars(port)
    hechos.append("Variables de entorno configuradas para los CLIs")
    return hechos


def uninstall() -> list[str]:
    hechos = []
    write_proxy_settings(False)
    hechos.append("Proxy del navegador desactivado")
    if untrust_ca():
        hechos.append("CA retirada del almacen del usuario")
    clear_env_vars()
    hechos.append("Variables de entorno eliminadas")
    return hechos


def main() -> int:
    from ..proxy import __name__ as _  # noqa: F401  (asegura el paquete)

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tests.e2e.harness import mitmdump_path

    accion = sys.argv[1] if len(sys.argv) > 1 else "status"
    puerto = int(os.environ.get("AEGIS_PORT", "8899"))

    if accion == "plan":
        for paso in plan(puerto):
            print(f"  - {paso.description}\n      {paso.detail}")
        codigo = 0
    else:
        if accion == "install":
            for hecho in install(puerto, mitmdump_path()):
                print(f"  {hecho}")
            codigo = 0
        else:
            if accion == "uninstall":
                for hecho in uninstall():
                    print(f"  {hecho}")
                codigo = 0
            else:
                for clave, valor in status(puerto).items():
                    print(f"  {clave}: {valor}")
                codigo = 0
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
