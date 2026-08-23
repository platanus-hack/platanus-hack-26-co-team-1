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

import os
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
    # El enrolamiento: `aegis enrolar` lo importa dentro de la funcion, igual
    # que el panel. Sin esto el instalador se descarga, protege el equipo, y no
    # puede afiliarse a ninguna empresa -- que es justo para lo que se publica.
    "aegis_agent.enrolar",
]

# Lo que NO va. Cada uno con su motivo, porque una lista de exclusiones sin
# explicacion es lo primero que alguien deshace sin saber que rompe.
# El paquete COMPLETO lleva T2 adentro. Se pide con AEGIS_COMPLETO=1.
#
# Existen los dos porque el modelo pesa mas que todo el resto junto -- torch son
# 432 MB, transformers 93 y los pesos 1.102 -- y la mayoria de la gente quiere
# probar el producto antes de decidir si le paga esa descarga. El liviano
# protege igual con T1, el diccionario y el OCR; el completo agrega lo unico que
# ve los datos de empresa, que no tienen formato.
#
# Se intento evitarlo exportando el modelo a ONNX, que habria dejado el paquete
# chico porque onnxruntime ya viaja por el OCR. No alcanza: `gliner/model.py`
# importa torch y transformers a nivel de MODULO, asi que sin ese arbol el
# modelo no se carga ni en ONNX. Y correr el ONNX a mano -- sin gliner -- obliga
# a reimplementar el armado de spans y el decodificado, donde un desajuste sutil
# no falla: detecta cero, en silencio. Queda anotado para hacerlo bien.
COMPLETO = os.environ.get("AEGIS_COMPLETO", "").strip() in ("1", "true", "si")

_solo_en_el_liviano = [
    "torch",           # 432 MB, solo lo necesita T2
    "gliner",          # idem
    "transformers",    # idem
]

excluidos = ([] if COMPLETO else list(_solo_en_el_liviano)) + [
    "playwright",      # solo los tests de navegador
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "unittest",        # el paquete no corre tests
]

# Los pesos del modelo, cuando el paquete es el completo.
#
# No alcanza con meter torch: `from_pretrained` se baja 1.102 MB de Hugging Face
# la primera vez, y un "instalador completo" que en el primer uso descarga un
# giga no es completo. Se copia el snapshot entero adentro y el agente lo busca
# ahi antes que en ningun otro lado (ver detect/model.py).
if COMPLETO:
    _hf = Path.home() / ".cache/huggingface/hub/models--urchade--gliner_multi-v2.1"
    _snaps = sorted(_hf.glob("snapshots/*")) if _hf.exists() else []
    if _snaps:
        # pytorch_model.bin NO va: es el MISMO modelo que model.safetensors, en
        # el formato viejo. Meter los dos sumaba 1.102 MB de nada y dejaba el zip
        # en 2.241 MB, arriba del limite de 2 GB por archivo de GitHub -- o sea
        # que el paquete completo no se podia ni publicar.
        _sobra = {"pytorch_model.bin", ".gitattributes", "README.md"}
        for _f in _snaps[-1].rglob("*"):
            if _f.is_file() and _f.name not in _sobra:
                datos.append((str(_f.resolve()), str(Path("modelo") / _f.parent.relative_to(_snaps[-1]))))
        print(f"paquete COMPLETO: {len(datos)} archivos de datos, modelo incluido")
    else:
        print("AVISO: AEGIS_COMPLETO pedido pero el modelo no esta en la cache de HF")


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
