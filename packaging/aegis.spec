# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para Aegis.exe.

Se corre con `python packaging/build_windows.py`, que es el que documenta el
proceso completo; este archivo es solo la receta.

## Las tres decisiones que tiene adentro

**one-folder y no one-file.** Un ejecutable de un solo archivo se descomprime
entero en el temporal cada vez que arranca, y esto arranca en cada inicio de
sesion: serian ciento treinta megas de descompresion antes de que el proxy
escuche, con el navegador ya apuntando a un puerto muerto. La carpeta arranca en
menos de un segundo.

**El OCR entra.** Son unos 67 MB entre rapidocr, onnxruntime y PIL, y es lo que
hace que una captura de pantalla no sea un canal invisible. Sin eso, `AEGIS_OCR=1`
en un equipo instalado no haria nada --y no haria nada en SILENCIO, que es peor.

**T2 no entra.** El modelo local necesita torch: 442 MB, cuatro veces todo el
resto del paquete junto. Queda como complemento para quien lo quiera, y el agente
protege igual sin el: hay tests que lo verifican.
"""

import sys
from pathlib import Path

RAIZ = Path(SPECPATH).resolve().parent
AGENTE = RAIZ / "agent"

# El OCR carga sus modelos desde archivos que viven dentro del paquete de
# rapidocr. PyInstaller no los ve porque no son imports: hay que copiarlos.
datos = []
try:
    import rapidocr_onnxruntime

    paquete = Path(rapidocr_onnxruntime.__file__).parent
    for archivo in list(paquete.rglob("*.onnx")) + list(paquete.rglob("*.yaml")):
        datos.append((str(archivo), str(Path("rapidocr_onnxruntime") / archivo.relative_to(paquete).parent)))
except ImportError:
    print("AVISO: rapidocr no esta instalado, el paquete va a salir sin OCR")

# pydivert NO se puede excluir, aunque solo lo use el modo transparente:
# `mitmproxy/platform/windows.py` lo importa al cargarse, y ese modulo lo importa
# `mitmproxy.addons.proxyserver`, o sea el camino normal. Excluirlo daba un exe que
# compilaba, pasaba `--help` y `plan`, y reventaba al levantar el proxy con
# "No module named pydivert". Pesa 0.3 MB: el ahorro no existia y el riesgo si.
ocultos = [
    "pydivert",
    "mitmproxy_windows",
    "mitmproxy.platform.windows",
    # mitmproxy arma su lista de addons por defecto en codigo, y la mayoria del
    # arbol se importa desde ahi. Estos son los que el analisis estatico no ve.
    "mitmproxy.addons",
    "mitmproxy.addons.dumper",
    "mitmproxy.proxy.layers",
    "mitmproxy.proxy.layers.http",
    "mitmproxy.contentviews",
    "mitmproxy.tools.dump",
    # Nuestro propio arbol: el CLI importa por nombre segun la accion.
    "aegis_agent.cli",
    "aegis_agent.servicio",
    "aegis_agent.install.windows",
    "aegis_agent.install.firewall",
    "aegis_agent.detect.ocr",
    "aegis_agent.detect.imagenes",
    # El panel y el interruptor. `aegis panel` los importa DENTRO de la funcion,
    # que es justo el caso que el analisis estatico puede no seguir -- y el modo
    # de falla es el que ya documenta pydivert mas arriba: un exe que compila,
    # pasa `--help` y revienta al usarlo.
    "aegis_agent.control",
    "aegis_agent.panel.server",
    "aegis_agent.panel.render",
    "aegis_agent.panel.metrics",
    # Lo que llego con las ultimas features. Van nombrados aunque hoy el
    # analisis los alcance: la lista es barata y olvidarse uno cuesta un exe
    # roto que solo se descubre usandolo.
    "aegis_agent.identidad",
    "aegis_agent.detect.ruleset",
]

# Lo que NO va. Cada uno con su motivo, porque una lista de exclusiones sin
# explicacion es lo primero que alguien deshace sin saber que rompe.
excluidos = [
    "torch",           # 442 MB, solo lo necesita T2, que es opcional por diseno
    "gliner",          # idem
    "transformers",    # idem
    "playwright",      # solo los tests de navegador
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "unittest",        # el paquete no corre tests
]

a = Analysis(
    # El envoltorio, NO el modulo del paquete. PyInstaller corre su script de
    # entrada como __main__, asi que un modulo con imports relativos revienta
    # --y solo en el ejecutable, que es donde nadie lo prueba. Ver agent/aegis.py.
    [str(AGENTE / "aegis.py")],
    pathex=[str(AGENTE)],
    binaries=[],
    datas=datos,
    hiddenimports=ocultos,
    excludes=excluidos,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aegis",
    debug=False,
    strip=False,
    upx=False,
    # Con consola: las acciones son de linea de comandos y el usuario tiene que
    # poder LEER lo que el instalador hizo. Un instalador de algo que se mete en
    # medio de todo tu trafico no puede ser una caja negra: el `plan` existe justo
    # para poder mostrarlo antes de tocar nada.
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Aegis",
)
