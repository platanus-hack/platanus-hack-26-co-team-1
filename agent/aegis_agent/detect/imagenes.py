"""Sacar las imagenes de un request, para que el pantallazo deje de ser invisible.

Esta mitad del problema no tiene nada de modelo: es plomeria, y va aparte del OCR
a proposito. Extraer las imagenes se puede probar sin instalar nada y sin pagar
un segundo de latencia; reconocer el texto no. Separarlas deja que la parte que
siempre corre sea barata y testeable.

## Las tres formas en que viaja una imagen hacia una IA

Medidas contra los cuerpos reales de los dos proveedores mas grandes:

    OpenAI     {"content": [{"type": "image_url",
                             "image_url": {"url": "data:image/png;base64,..."}}]}
    Anthropic  {"content": [{"type": "image",
                             "source": {"type": "base64", "data": "..."}}]}
    subida     multipart con Content-Type: image/* , o el binario crudo como body

No se reconoce proveedor por proveedor sino que se recorre el arbol buscando lo
que parezca una imagen, por el mismo motivo que `prompt.py` recorre en vez de
enumerar: las formas se parecen todas y una forma nueva no deberia necesitar un
release.
"""

from __future__ import annotations

import base64
import binascii
import json
import re

# Cuantas imagenes se miran por request. Un cuerpo armado a proposito puede traer
# cien miniaturas y el OCR cuesta segundos, no milisegundos.
MAX_IMAGENES = 4

# Tope por imagen. Una captura de pantalla de una pantalla 4K comprimida ronda el
# megabyte; arriba de eso es un archivo, y un archivo grande ya lo miran las
# firmas binarias de files.py.
MAX_BYTES_POR_IMAGEN = 8_000_000

FIRMAS: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",  # jpeg
    b"GIF87a",
    b"GIF89a",
    b"RIFF",  # webp (lleva WEBP en el byte 8)
    b"BM",  # bmp
    b"II*\x00",  # tiff
    b"MM\x00*",
)

_DATA_URI = re.compile(r"data:image/[a-z.+-]{2,12};base64,([A-Za-z0-9+/=\s]{64,})")

# Claves donde los proveedores ponen los bytes de una imagen.
_CLAVES_DE_IMAGEN = frozenset({"data", "url", "b64_json", "image", "image_data"})

MAX_PROFUNDIDAD = 12


def es_imagen(datos: bytes) -> bool:
    return datos.startswith(FIRMAS)


def _de_base64(texto: str) -> bytes:
    limpio = "".join(texto.split())
    relleno = limpio + "=" * (-len(limpio) % 4)
    try:
        datos = base64.b64decode(relleno, validate=False)
    except (binascii.Error, ValueError):
        datos = b""
    return datos


def _del_arbol(nodo: object, profundidad: int = 0) -> list[bytes]:
    """Recorre el JSON juntando lo que decodifique a una imagen.

    No se filtra por el nombre del tipo de bloque ("image_url", "image") sino por
    la FIRMA de lo que sale al decodificar. Es mas barato de mantener y no se
    puede esquivar renombrando una clave.
    """

    encontradas: list[bytes] = []
    if profundidad <= MAX_PROFUNDIDAD:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if isinstance(valor, str):
                    if clave.lower() in _CLAVES_DE_IMAGEN and len(valor) > 64:
                        crudo = valor
                        marca = crudo.find("base64,")
                        if marca >= 0:
                            crudo = crudo[marca + len("base64,") :]
                        datos = _de_base64(crudo)
                        if es_imagen(datos):
                            encontradas.append(datos)
                else:
                    encontradas.extend(_del_arbol(valor, profundidad + 1))
        elif isinstance(nodo, list):
            for elemento in nodo:
                encontradas.extend(_del_arbol(elemento, profundidad + 1))
    return encontradas


def _de_data_uris(texto: str) -> list[bytes]:
    """Las data: URI que quedaron en el texto, sin pasar por el arbol.

    Cubre el cuerpo que no es JSON valido y el JSON que no se pudo parsear, que
    es justo el caso del shadow AI todavia sin catalogar: recortar ahi seria
    recortar el caso peligroso.
    """

    encontradas: list[bytes] = []
    for match in _DATA_URI.finditer(texto):
        datos = _de_base64(match.group(1))
        if es_imagen(datos):
            encontradas.append(datos)
    return encontradas


_CORRIDA_BASE64 = re.compile(r"[A-Za-z0-9+/]{64,}={0,2}")
MAX_CORRIDAS = 12

# Cuanto se decodifica para probar la firma. Solo la cabeza: decodificar entero
# cada corrida larga de un cuerpo grande cuesta, y para saber si es una imagen
# alcanzan los primeros bytes.
_CABEZA_BASE64 = 32


def _de_base64_suelto(texto: str) -> list[bytes]:
    """Las corridas de base64 que resultan ser una imagen, sin data: ni JSON.

    Es el ultimo recurso y cubre el caso que importa: un cuerpo que no se pudo
    parsear. El shadow AI que todavia no esta en ninguna lista tampoco tiene una
    forma conocida, y ahi recortar seria recortar justo el caso peligroso.

    Se prueba la FIRMA sobre los primeros bytes y solo se decodifica entero lo
    que ya dio positivo: al reves, un cuerpo grande con muchas corridas costaria
    una decodificacion completa por cada una.
    """

    encontradas: list[bytes] = []
    for indice, match in enumerate(_CORRIDA_BASE64.finditer(texto)):
        if indice >= MAX_CORRIDAS or len(encontradas) >= MAX_IMAGENES:
            break
        corrida = match.group(0)
        if not es_imagen(_de_base64(corrida[:_CABEZA_BASE64])):
            continue
        datos = _de_base64(corrida)
        if es_imagen(datos):
            encontradas.append(datos[:MAX_BYTES_POR_IMAGEN])
    return encontradas


def _de_multipart(payload: bytes) -> list[bytes]:
    """Las partes de un formulario cuyo contenido es una imagen.

    Se busca la firma dentro de cada parte en vez de leer su Content-Type: el
    cliente controla ese encabezado, y renombrar un archivo es la evasion mas
    barata que existe. Es la misma decision que ya toma files.py.
    """

    encontradas: list[bytes] = []
    for firma in FIRMAS:
        desde = 0
        while len(encontradas) < MAX_IMAGENES:
            desde = payload.find(firma, desde)
            if desde < 0:
                break
            encontradas.append(payload[desde : desde + MAX_BYTES_POR_IMAGEN])
            desde += len(firma)
    return encontradas


def extraer(payload: bytes | None, texto: str = "") -> list[bytes]:
    """Las imagenes que lleva este request, hasta MAX_IMAGENES.

    Se devuelven los bytes y no un objeto de imagen para que este modulo no
    dependa de PIL: quien decide si hay con que abrirlas es el OCR, que es la
    pieza opcional.
    """

    cuerpo = payload or b""
    encontradas: list[bytes] = []

    if es_imagen(cuerpo):
        encontradas.append(cuerpo[:MAX_BYTES_POR_IMAGEN])

    if not encontradas and texto:
        recorte = texto.lstrip()
        if recorte[:1] in ("{", "["):
            try:
                encontradas.extend(_del_arbol(json.loads(recorte)))
            except (ValueError, RecursionError):
                pass
        if len(encontradas) < MAX_IMAGENES:
            encontradas.extend(_de_data_uris(texto))
        if not encontradas:
            encontradas.extend(_de_base64_suelto(texto))

    if not encontradas and b"filename=" in cuerpo[:4096]:
        encontradas.extend(_de_multipart(cuerpo))

    # Dedup por contenido: la misma imagen en el arbol y en la data: URI del
    # texto es una sola imagen, y el OCR cuesta demasiado para pagarlo dos veces.
    vistas: list[bytes] = []
    huellas: set[int] = set()
    for datos in encontradas:
        huella = hash(datos)
        if huella not in huellas and len(datos) <= MAX_BYTES_POR_IMAGEN:
            huellas.add(huella)
            vistas.append(datos)
    return vistas[:MAX_IMAGENES]
