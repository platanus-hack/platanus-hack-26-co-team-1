"""Arma el paquete descargable para Windows.

    python packaging/build_windows.py            # compila y empaqueta
    python packaging/build_windows.py --probar    # y ademas prueba el .exe

Deja `dist/Aegis-windows.zip`: la persona lo baja, lo descomprime y hace doble
clic en `Instalar Aegis.bat`. No necesita Python, ni pip, ni saber que existe una
linea de comandos.

## Lo que hay que saber antes de tocar esto

**Se compila con el Python en el que estan las dependencias.** PyInstaller
empaqueta lo que ve en SU entorno, asi que si mitmproxy no esta instalado en el
interprete que corre este script, el paquete sale sin mitmproxy y el error se
descubre recien al ejecutarlo. Por eso `--probar` existe y por eso conviene usarlo:
un paquete roto se ve exactamente igual que uno bueno hasta que alguien lo abre.

**El paquete queda atado a la version de Windows y a la arquitectura** donde se
compilo. No es un problema hoy --es una herramienta interna para equipos
Windows-- pero no se puede compilar en Linux y esperar que corra.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIST = RAIZ / "dist"
CARPETA = DIST / "Aegis"
ZIP = DIST / "Aegis-windows.zip"

# Los .bat existen para que el usuario no tenga que abrir una consola ni escribir
# nada. El `pause` del final NO es decorativo: sin eso la ventana se cierra sola y
# la persona no llega a leer que hizo el instalador --ni el mensaje de la CA, que
# es el unico paso donde tiene que hacer algo.
INSTALAR_BAT = """@echo off
chcp 65001 > nul
title Instalar Aegis
echo.
echo   Aegis se va a poner en medio de tu trafico hacia servicios de IA
echo   para avisarte antes de que salga informacion que no deberia salir.
echo.
echo   Esto es lo que va a hacer:
echo.
"%~dp0Aegis.exe" plan
echo.
echo   ----------------------------------------------------------------
echo   Windows te va a pedir permiso para confiar en el certificado de
echo   Aegis. Hay que ACEPTAR: sin eso, cada sitio seguro te va a
echo   mostrar una advertencia.
echo   ----------------------------------------------------------------
echo.
pause
echo.
"%~dp0Aegis.exe" instalar
echo.
"%~dp0Aegis.exe" estado
echo.
pause
"""

DESINSTALAR_BAT = """@echo off
chcp 65001 > nul
title Desinstalar Aegis
echo.
echo   Quitando Aegis de tu equipo. No queda nada atras.
echo.
"%~dp0Aegis.exe" desinstalar
echo.
pause
"""

PANEL_BAT = """@echo off
chcp 65001 > nul
title Panel de Aegis
echo.
echo   Abriendo el panel de Aegis en tu navegador.
echo   Ahi ves lo que Aegis reviso y podes prenderlo o apagarlo.
echo.
echo   Esta ventana tiene que quedar abierta mientras uses el panel.
echo   Cerrala (o Ctrl+C) para cerrarlo. Aegis sigue funcionando igual.
echo.
"%~dp0Aegis.exe" panel
"""

ESTADO_BAT = """@echo off
chcp 65001 > nul
title Estado de Aegis
"%~dp0Aegis.exe" estado
echo.
pause
"""

# El paso que faltaba, y sin el la mitad del producto no existe.
#
# Instalar deja el equipo PROTEGIDO. Enrolar decide A QUIEN LE REPORTA. Son dos
# cosas distintas a proposito (ver aegis_agent/enrolar.py), pero hasta aca el
# paquete solo ofrecia la primera: cuatro .bat, ninguno para enrolar, y el LEEME
# sin mencionar la palabra. La persona hacia doble clic, quedaba protegida, y no
# le hablaba a ningun panel. La empresa veia su panel vacio y concluia que nadie
# usa IA -- exactamente la falla que enrolar.py documenta como su razon de ser.
# El comando existia desde el principio; lo que faltaba era el doble clic.
#
# No se pide el codigo con `set /p`: se llama al exe sin argumento y el propio
# comando lo pide (cli.py lo hace cuando stdin es una consola). Asi el texto que
# lee la persona vive en un solo lugar, y no hay que pelear con el escapado de
# batch para una cadena que la gente va a pegar con guiones.
ENROLAR_BAT = """@echo off
chcp 65001 > nul
title Conectar Aegis con tu empresa
echo.
echo   Vas a conectar este equipo con el panel de tu empresa.
echo.
echo   Necesitas el codigo que te dieron: son cuatro letras o numeros,
echo   un guion, y otros cuatro. Algo como AEGIS-4K7M-9PQR.
echo.
echo   Esto NO instala ni cambia nada de tu equipo, y no manda nada de lo
echo   que escribis: solo deja anotado a que panel avisar.
echo.
"%~dp0Aegis.exe" enrolar
echo.
echo   ----------------------------------------------------------------
"%~dp0Aegis.exe" estado
echo.
pause
"""

LEEME = """AEGIS
=====

Aegis se pone entre tu computadora y los servicios de inteligencia artificial
--ChatGPT, Claude, Copilot, Gemini y unos ciento setenta mas-- y revisa, EN TU
PROPIO EQUIPO, si lo que estas por enviar contiene informacion que no deberia
salir: una contrasena, una cedula, un contrato, una base de clientes.

Cuando encuentra algo, te lo explica antes de que salga.


PARA INSTALARLO
---------------

  1. Doble clic en "Instalar Aegis.bat"
  2. Windows te va a pedir permiso para confiar en el certificado de Aegis.
     Hay que ACEPTAR. Sin eso, cada sitio seguro te va a mostrar una
     advertencia y Aegis no se activa.
  3. Listo. Desde ahora arranca solo cada vez que inicias sesion.

Para ver como esta: "Estado de Aegis.bat"
Para sacarlo:       "Desinstalar Aegis.bat"


PARA CONECTARLO CON TU EMPRESA
------------------------------

Instalarlo te protege a vos. Conectarlo es lo que hace que tu empresa vea que
esta pasando --sin ver nunca lo que escribis-- y lo que le permite mandarte su
propia configuracion: que considera sensible, que sitios tiene aprobados.

  1. Pedile el codigo a quien administra Aegis en tu empresa. Son cuatro
     letras o numeros, un guion, y otros cuatro: AEGIS-4K7M-9PQR.
  2. Doble clic en "Conectar con mi empresa.bat" y pegalo.

Son dos pasos separados a proposito. Instalar decide si este equipo esta
protegido; conectar decide a quien le reporta. Podes hacerlos en cualquier
orden, y volver a conectar te cambia de empresa sin desinstalar nada.

Si no lo conectas, Aegis igual te protege: bloquea, avisa y te explica. Lo que
no pasa es que nadie mas se entere, ni que te llegue la configuracion de tu
empresa.


EL PANEL
--------

Doble clic en "Panel de Aegis.bat" y se abre en tu navegador. Ahi ves que
reviso Aegis --que tipo de dato se intento enviar y hacia donde, nunca el
dato-- y arriba de todo hay un interruptor para prenderlo y apagarlo.

Apagarlo NO lo desinstala: deja de revisar el trafico y nada mas, asi que
volver a prenderlo es instantaneo. Sirve para probar si algo se rompe por
culpa de Aegis, o para mostrar la diferencia entre tenerlo y no tenerlo.


LO QUE AEGIS *NO* HACE
----------------------

Esto importa mas que la lista de lo que si hace, asi que va primero.

  * NO manda lo que escribis a ningun servidor. La decision de bloquear o
    dejar pasar se toma completa en tu equipo, sin conexion. Lo unico que
    sale es un aviso sin contenido: "salio una credencial hacia tal sitio",
    nunca el texto, nunca la direccion completa, nunca tu nombre real.

  * NO mira tu banco, tu prestadora de salud ni las paginas del gobierno.
    Esas conexiones ni se abren: pasan de largo sin descifrarse.

  * NO necesita permisos de administrador y no cambia nada a nivel de la
    maquina. Todo queda en tu usuario y se revierte con un clic.


SI ALGO SALE MAL
----------------

Si en algun momento no tenes internet, es porque tu navegador esta apuntando a
Aegis y Aegis no esta corriendo. Corre "Estado de Aegis.bat": te lo va a decir
en una linea. Y "Desinstalar Aegis.bat" te devuelve todo como estaba, siempre.


LO OPCIONAL
-----------

  * Leer el texto de las capturas de pantalla ya viene incluido, pero apagado,
    porque tarda unos dos segundos por imagen. Se prende desde el panel, en
    Deteccion. Sirve para lo que nadie transcribe a mano: la foto de una
    pantalla con una contrasena o una cedula.

  * El modelo local que detecta datos sin formato (nombres de clientes, cifras
    de contratos) NO viene en este paquete: necesita 442 MB de dependencias.
    Aegis protege igual sin el.
"""


def _requisitos() -> list[str]:
    faltan = []
    for modulo, para_que in (
        ("PyInstaller", "compilar"),
        ("mitmproxy", "el proxy"),
    ):
        try:
            __import__(modulo)
        except ImportError:
            faltan.append(f"{modulo} (hace falta para {para_que})")
    return faltan


def compilar() -> None:
    faltan = _requisitos()
    if faltan:
        print("No se puede compilar, falta:")
        for cual in faltan:
            print(f"  - {cual}")
        print(f"\n  {sys.executable} -m pip install pyinstaller -r agent/requirements.txt")
        raise SystemExit(1)

    if CARPETA.exists():
        shutil.rmtree(CARPETA)

    print(f"Compilando con {sys.executable}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(RAIZ / "build"),
            "--log-level",
            "WARN",
            str(RAIZ / "packaging" / "aegis.spec"),
        ],
        cwd=str(RAIZ),
        check=True,
    )


def agregar_lanzadores() -> None:
    (CARPETA / "Instalar Aegis.bat").write_text(INSTALAR_BAT, encoding="utf-8")
    (CARPETA / "Desinstalar Aegis.bat").write_text(DESINSTALAR_BAT, encoding="utf-8")
    (CARPETA / "Estado de Aegis.bat").write_text(ESTADO_BAT, encoding="utf-8")
    (CARPETA / "Conectar con mi empresa.bat").write_text(ENROLAR_BAT, encoding="utf-8")
    (CARPETA / "Panel de Aegis.bat").write_text(PANEL_BAT, encoding="utf-8")
    (CARPETA / "LEEME.txt").write_text(LEEME, encoding="utf-8")


def probar() -> bool:
    """Que el ejecutable arranque y sepa quien es.

    Sin esto no hay forma de distinguir un paquete bueno de uno roto: los dos
    pesan lo mismo y los dos tienen un .exe adentro. Se prueban las acciones que
    NO tocan el sistema.
    """

    exe = CARPETA / "Aegis.exe"
    if not exe.exists():
        print(f"  FALLO: no existe {exe}")
        return False

    ok = True
    # Estas dos son baratas pero NO alcanzan, y eso se aprendio de la peor forma:
    # un paquete paso las dos y reventaba al levantar el proxy, porque ni --help ni
    # plan importan el stack de mitmproxy. La prueba que vale es la de abajo.
    for accion, esperado in (("--help", "aegis instalar"), ("plan", "Generar la CA")):
        resultado = subprocess.run(
            [str(exe), accion], capture_output=True, text=True, timeout=120, errors="replace"
        )
        salida = resultado.stdout + resultado.stderr
        if esperado in salida:
            print(f"  OK   Aegis.exe {accion}")
        else:
            print(f"  FALLO Aegis.exe {accion}: no aparecio {esperado!r}")
            print("       " + salida.strip().replace("\n", "\n       ")[:600])
            ok = False
    return ok and _levanta_el_proxy(exe) and _abre_el_panel(exe)


def _levanta_el_proxy(exe: Path) -> bool:
    """Que el proxy ARRANQUE de verdad y escuche. Es la unica prueba que vale.

    `--help` y `plan` no importan nada de mitmproxy, asi que un paquete al que le
    falte una dependencia del proxy las pasa las dos y falla recien cuando alguien
    lo instala. Paso: sin pydivert el exe compilaba, respondia `plan` perfecto y
    moria con "No module named pydivert" al levantar el servicio.

    No se toca nada del sistema: puerto propio, y el proceso se mata al terminar.
    """

    import os
    import socket
    import time

    puerto = 8917
    entorno = {
        **os.environ,
        "AEGIS_PORT": str(puerto),
        "AEGIS_BACKEND_DISABLED": "1",
        "AEGIS_SENSOR": "0",
    }
    proceso = subprocess.Popen(
        [str(exe), "servicio"],
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )

    def escucha() -> bool:
        with socket.socket() as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", puerto)) == 0

    try:
        limite = time.time() + 60
        while time.time() < limite:
            if proceso.poll() is not None:
                print("  FALLO Aegis.exe servicio murio al arrancar:")
                salida = (proceso.stdout.read() or "").strip()
                for linea in salida.splitlines()[-25:]:
                    print(f"       {linea}")
                return False
            if escucha():
                print(f"  OK   Aegis.exe servicio escucha en {puerto}")
                return True
            time.sleep(0.5)
        print("  FALLO Aegis.exe servicio no escucho en 60 s")
        return False
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proceso.kill()


def _abre_el_panel(exe: Path) -> bool:
    """Que `aegis panel` levante y sirva, no solo que el exe tenga el archivo.

    Es el mismo riesgo que el del proxy y por el mismo motivo: `_panel` importa
    el servidor DENTRO de la funcion, que es justo el caso donde el analisis
    estatico de PyInstaller puede no seguir. Un paquete al que le falte
    `aegis_agent.panel.server` pasa `--help`, pasa `plan`, levanta el proxy, y
    revienta cuando la persona abre el panel: o sea, en la unica pantalla que va
    a mirar.

    Ademas se pide una pagina de verdad, no solo que el puerto abra: si el
    render fallara, el servidor escucharia igual y la persona veria un error 500.
    """

    import os
    import socket
    import time
    import urllib.error
    import urllib.request

    puerto = 8918
    entorno = {**os.environ, "AEGIS_PANEL_PORT": str(puerto), "AEGIS_SENSOR": "0"}
    proceso = subprocess.Popen(
        [str(exe), "panel"],
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )

    def escucha() -> bool:
        with socket.socket() as s:
            s.settimeout(0.4)
            return s.connect_ex(("127.0.0.1", puerto)) == 0

    try:
        limite = time.time() + 60
        while time.time() < limite and not escucha():
            if proceso.poll() is not None:
                print("  FALLO Aegis.exe panel murio al arrancar:")
                salida = (proceso.stdout.read() or "").strip()
                for linea in salida.splitlines()[-25:]:
                    print(f"       {linea}")
                return False
            time.sleep(0.5)

        if not escucha():
            print("  FALLO Aegis.exe panel no escucho en 60 s")
            return False

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/", timeout=10
            ) as respuesta:
                html = respuesta.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as error:
            print(f"  FALLO Aegis.exe panel no sirvio la pagina: {error}")
            return False

        if "id=\"switch\"" not in html:
            print("  FALLO Aegis.exe panel sirvio una pagina sin el interruptor")
            return False

        print(f"  OK   Aegis.exe panel sirve el interruptor en {puerto}")
        return True
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proceso.kill()


def empaquetar() -> Path:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for archivo in sorted(CARPETA.rglob("*")):
            if archivo.is_file():
                z.write(archivo, Path("Aegis") / archivo.relative_to(CARPETA))
    return ZIP


def main() -> int:
    compilar()
    agregar_lanzadores()

    if "--probar" in sys.argv and not probar():
        print("\nEl ejecutable no pasa la prueba: no se empaqueta.")
        return 1

    destino = empaquetar()
    tamano = destino.stat().st_size / 1e6
    carpeta = sum(f.stat().st_size for f in CARPETA.rglob("*") if f.is_file()) / 1e6
    print(f"\n  {destino}")
    print(f"  {tamano:.0f} MB comprimido, {carpeta:.0f} MB descomprimido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
