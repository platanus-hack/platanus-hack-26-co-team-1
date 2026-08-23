"""Lo que cambia entre correr desde el repo y correr desde un ejecutable.

## Por que existe este modulo

El agente se instalaba con `python -m aegis_agent.install.windows install`, que
es un flujo de desarrollador: pide Python, pip y saber que comando escribir.
Para que un empleado pueda descargarlo y usarlo hace falta un ejecutable, y ahi
dos supuestos del codigo dejan de valer:

1. **Que exista `mitmdump.exe`.** Adentro de un ejecutable empaquetado no hay
   `Scripts/`, no hay entorno virtual y no hay ningun `.exe` de terceros al lado
   del interprete. Peor: la busqueda de ese ejecutable vivia en
   `tests/e2e/harness.py`, o sea que **el instalador de produccion importaba un
   modulo de tests**, y los tests no se empaquetan.

2. **Que se pueda pasar un script por ruta.** mitmproxy carga los addons con
   `-s archivo.py`, y adentro de un ejecutable ese archivo no esta en el disco.

Los dos se resuelven usando mitmproxy **como biblioteca** en vez de como
programa: `CertStore` genera la CA sin arrancar nada, y `DumpMaster` levanta el
proxy con el addon agregado en memoria. Medido: las dos cosas funcionan, y de
paso el arranque deja de depender de que un `.exe` de terceros este en el PATH,
que era una fuente de fallas silenciosas tambien fuera del paquete.
"""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path

# Donde mitmproxy guarda su autoridad certificadora. No se cambia: es la ruta que
# el propio mitmproxy usa por defecto y la que el instalador ya sabe leer.
DIRECTORIO_CA = Path.home() / ".mitmproxy"
CA_CER = DIRECTORIO_CA / "mitmproxy-ca-cert.cer"
CA_PEM = DIRECTORIO_CA / "mitmproxy-ca-cert.pem"

TAMANO_DE_LLAVE = 2048

PUERTO_POR_DEFECTO = 8899


def empaquetado() -> bool:
    """Corriendo desde un ejecutable armado con PyInstaller."""

    return bool(getattr(sys, "frozen", False))


def puerto() -> int:
    try:
        valor = int(os.environ.get("AEGIS_PORT", str(PUERTO_POR_DEFECTO)))
    except ValueError:
        valor = PUERTO_POR_DEFECTO
    return valor


def ejecutable_del_agente() -> list[str]:
    """Como volver a invocarse a si mismo.

    Lo necesita el arranque automatico: la entrada del registro tiene que decir
    que ejecutar cuando la persona prende la maquina, y eso es distinto segun si
    esto es un .exe o un modulo de Python.
    """

    if empaquetado():
        comando = [sys.executable]
    else:
        comando = [sys.executable, "-m", "aegis_agent.cli"]
    return comando


def lanzar_desprendido(argumentos: list[str], extra: dict | None = None):
    """Arranca al propio agente en un proceso que sobrevive a este. None si no.

    Estaba escrito dos veces --`cli._arrancar_en_segundo_plano` y
    `guardian.lanzar`-- y las dos copias YA habian empezado a separarse: una
    pasaba `env` y la otra no. Un proceso que hay que desprender bien es
    exactamente la clase de detalle que no conviene tener en dos lados.

    Sin CREATE_NO_WINDOW aparece una consola negra en la cara de la persona cada
    vez que inicia sesion, y eso no dura instalado una semana. DETACHED_PROCESS
    es lo que hace que siga vivo cuando quien lo lanzo se muere, que es todo el
    punto del guardian.
    """

    import subprocess

    banderas = 0
    if os.name == "nt":
        banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    try:
        proceso = subprocess.Popen(
            ejecutable_del_agente() + argumentos,
            env={**os.environ, **(extra or {})},
            creationflags=banderas,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        proceso = None
    return proceso


def windows_apunta_a_aegis(puerto_esperado: int) -> bool:
    """Si el proxy configurado en Windows es este Aegis y no otra cosa.

    Tambien estaba dos veces, con dos nombres que no se parecian en nada
    --`cli.windows_apunta_a_aegis` y `guardian.hay_que_actuar`-- y cuerpos
    identicos byte a byte. Importa que sea uno solo: el guardian APAGA el proxy
    cuando esto da True, asi que el dia que la definicion de "es Aegis" cambie y
    solo cambie de un lado, el guardian apagaria el proxy que la persona
    configuro a mano hacia otra cosa.
    """

    try:
        from .install import windows

        estado = windows.read_proxy_settings()
        apunta = bool(estado["enabled"]) and estado["server"] == f"127.0.0.1:{puerto_esperado}"
    except Exception:
        # Sin registro que leer --otro sistema operativo, permisos-- la
        # respuesta honesta es "no se sabe", y no se toca nada.
        apunta = False
    return apunta


def generar_ca() -> bool:
    """Crea la autoridad certificadora si no existe. Sin arrancar ningun proceso.

    Antes esto lanzaba `mitmdump --listen-port 0` y esperaba hasta treinta
    segundos a que el archivo apareciera en disco: un proceso entero levantado
    como efecto secundario, con un sleep-y-mirar en el medio. `CertStore` la
    escribe directo, y ademas funciona adentro de un ejecutable donde no hay
    ningun mitmdump que lanzar.
    """

    if CA_CER.exists():
        listo = True
    else:
        try:
            from mitmproxy import certs

            DIRECTORIO_CA.mkdir(parents=True, exist_ok=True)
            certs.CertStore.from_store(
                str(DIRECTORIO_CA), "mitmproxy", TAMANO_DE_LLAVE
            )
            listo = CA_CER.exists()
        except Exception:
            listo = False
    return listo


def mitmdump_en_disco() -> str | None:
    """El ejecutable de mitmproxy, si esta. Solo para el camino de desarrollo.

    Ya no hace falta para levantar el proxy --eso ahora es en proceso-- pero los
    tests de punta a punta arrancan un proxy de verdad como subproceso, y para eso
    el ejecutable sigue siendo lo mas simple.

    Vivia en tests/e2e/harness.py y lo importaba el instalador de produccion. Un
    modulo de tests no se empaqueta, asi que en un ejecutable ese import
    reventaba: el instalador tenia una dependencia que no podia existir donde mas
    importaba que funcionara.
    """

    nombre = "mitmdump.exe" if os.name == "nt" else "mitmdump"
    esquema = "nt_user" if os.name == "nt" else "posix_user"
    candidatos = (
        Path(sys.executable).parent / nombre,
        Path(sys.executable).parent / "Scripts" / nombre,
        Path(sysconfig.get_path("scripts")) / nombre,
        Path(sysconfig.get_path("scripts", scheme=esquema)) / nombre,
    )
    encontrado: str | None = None
    for candidato in candidatos:
        if candidato.exists():
            encontrado = str(candidato)
            break
    return encontrado
