"""Reconocer una subida de archivo hacia una IA, aunque el destino no sea la IA.

## El agujero que cierra este modulo

Cuando alguien arrastra un archivo a ChatGPT, los bytes **no van a
chatgpt.com**: van a ``files.oaiusercontent.com``. Y para el catalogo ese host
es ``non_ai``, asi que el camino completo del addon lo descarta:

    el destino no es IA  ->  ¿tiene forma de llamada a un modelo?  ->  no  ->  fin

Medido: ``looks_like_ai_api`` devuelve False para un PUT de archivo y para un
multipart con ``filename=``, porque busca la forma de una *conversacion* --las
claves ``messages``, ``prompt``, ``model``-- y una subida no tiene ninguna. El
resultado es que **la accion mas comun y mas facil de sacar un documento entero
no dispara nada**, y no por una regla que falte sino por un agujero en el embudo,
que es la pieza que sostiene todo el diseno.

Esto no se arregla agrandando la lista de dominios. La lista es el piso (ADR
0002) y los endpoints de subida cambian de nombre; ademas el mismo host de blobs
sirve para cosas que no son IA. Lo que se arregla es la pregunta: hasta ahora el
embudo preguntaba *"¿esto parece un chat?"* y hay que preguntar tambien *"¿esto
parece un archivo yendose, y yendose hacia una IA?"*.

## Las dos senales, y por que estas

**1. El origen de la pestana.** Cuando la pagina de ChatGPT sube un archivo, el
navegador pone ``Origin: https://chatgpt.com`` en el request al host de blobs.
No hay que adivinar nada ni guardar estado: el propio request dice de quien es.
Cubre todas las subidas desde el navegador, que son la mayoria, y es
deterministico.

**2. El endpoint de subida conocido.** Para lo que no manda ``Origin`` --una app
de escritorio, un CLI-- quedan los hosts de subida que ya se conocen, en el
catalogo. Es el piso, con la misma limitacion que cualquier lista.

## Lo que este modulo NO hace, a proposito

No correlaciona por proceso ni por ventana de tiempo. La correlacion por proceso
es la senal que faltaria para cubrir la app de escritorio que no manda
``Origin``, y **la esta construyendo otra tarea** (``procesos.py``, ADR 0004):
duplicarla aca seria dos mecanismos peleandose por la misma decision. El punto de
enganche esta marcado abajo con un TODO y es una linea.

Y no le dice nada al detector. El detector sigue recibiendo texto y destino, sin
saber que aplicacion lo origino (ADR 0002). Lo que este modulo cambia es la
*clasificacion del destino*, que es donde vive esa decision.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Tipos de contenido que son un archivo yendose, no una conversacion. Se
# comparan por prefijo para que "image/png" y "image/heic" entren igual.
TIPOS_DE_ARCHIVO: tuple[str, ...] = (
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "application/x-zip",
    "application/gzip",
    "application/x-tar",
    "application/vnd.openxmlformats",  # docx, xlsx, pptx
    "application/vnd.ms-",  # doc, xls, ppt
    "application/msword",
    "application/vnd.oasis",  # odt, ods
    "application/x-sqlite3",
    "application/sql",
    "text/csv",
    "image/",
    "audio/",
    "video/",
)

# Firmas de archivo, para el caso en que el Content-Type miente o no viene. Es la
# misma idea que detect/files.py: el archivo es lo que es, no lo que dice.
FIRMAS: tuple[bytes, ...] = (
    b"PK\x03\x04",  # zip, docx, xlsx
    b"%PDF",
    b"\x89PNG",
    b"\xff\xd8\xff",  # jpeg
    b"GIF8",
    b"RIFF",  # wav, webp
    b"ID3",  # mp3
    b"\x1f\x8b",  # gzip
    b"SQLite format 3\x00",
    b"PGDMP",
    b"\xd0\xcf\x11\xe0",  # doc, xls antiguos
    b"OggS",
    b"\x00\x00\x00\x1cftyp",  # mp4/m4a
)

# Cuanto del cuerpo alcanza para reconocer una firma o un encabezado multipart.
PREFIJO = 512


def _tipo_de_archivo(content_type: str) -> bool:
    tipo = content_type.split(";", 1)[0].strip().lower()
    return any(tipo.startswith(prefijo) for prefijo in TIPOS_DE_ARCHIVO)


def _multipart_con_archivo(content_type: str, prefijo: bytes) -> bool:
    """Un formulario que lleva un archivo, y no solo campos de texto.

    La diferencia es ``filename=``: un multipart sin eso es un formulario
    corriente y su texto ya lo mira el motor como cualquier otro cuerpo.
    """

    es_multipart = "multipart/form-data" in content_type.lower()
    return es_multipart and b"filename=" in prefijo


def es_subida_de_archivo(content_type: str, cuerpo: bytes | None) -> bool:
    """El request lleva un archivo hacia afuera."""

    prefijo = (cuerpo or b"")[:PREFIJO]
    if _multipart_con_archivo(content_type, prefijo):
        resultado = True
    elif _tipo_de_archivo(content_type):
        resultado = True
    else:
        resultado = any(prefijo.startswith(firma) for firma in FIRMAS)
    return resultado


def _host_de(url: str) -> str:
    """El host de un Origin o de un Referer, tolerante con lo que llegue."""

    recorte = url.strip()
    if recorte:
        partido = urlsplit(recorte if "//" in recorte else "//" + recorte)
        host = (partido.hostname or "").lower()
    else:
        host = ""
    return host


def ia_que_origina(origin: str, referer: str, es_ia) -> str | None:
    """El host de IA desde cuya pagina se disparo este request, si lo hay.

    ``es_ia`` recibe un host y dice si es un servicio de IA. Se pasa como
    parametro y no se importa para que este modulo no dependa de la politica:
    quien llama ya tiene la politica en la mano y sabe clasificar.
    """

    encontrado: str | None = None
    for candidato in (origin, referer):
        host = _host_de(candidato)
        if host and es_ia(host):
            encontrado = host
            break
    return encontrado


def subida_hacia_una_ia(
    content_type: str,
    cuerpo: bytes | None,
    origin: str,
    referer: str,
    es_ia,
) -> str | None:
    """El host de IA a la que se le esta subiendo un archivo, o None.

    Devolver el host y no un booleano es a proposito: el evento del panel tiene
    que decir *a que IA* se fue el documento, no que "hubo una subida". Para la
    persona que mira el panel, "un archivo salio hacia ChatGPT" y "un archivo
    salio hacia algun lado" no son la misma frase.
    """

    if not es_subida_de_archivo(content_type, cuerpo):
        destino = None
    else:
        destino = ia_que_origina(origin, referer, es_ia)
        # TODO(procesos): cuando aterrice la atribucion por proceso (ADR 0004),
        # el caso que falta --la app de escritorio que no manda Origin-- se cubre
        # preguntandole a procesos.py si el proceso que abrio esta conexion es el
        # mismo que tiene una sesion de IA abierta. Es una linea aca y evita
        # tener dos mecanismos decidiendo lo mismo.
    return destino
