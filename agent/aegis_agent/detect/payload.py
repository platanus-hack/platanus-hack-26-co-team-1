from __future__ import annotations

import base64
import binascii
import io
import json
import re
import unicodedata
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote_plus

from . import diccionario
from . import ocr
from .engine import scan
from .files import scan_files
from .imagenes import extraer as extraer_imagenes
from .model import scan_model
from .prompt import extract_prompt
from .types import Finding

# Un secreto casi nunca viaja en texto plano y derecho: viaja dentro de un JSON
# escapado, de un multipart, de un .docx (que es un zip), en base64 o en un body
# comprimido. Escanear solo lo que llega tal cual es lo que hace que un DLP se
# pueda esquivar sin proponerselo, simplemente adjuntando un archivo.

MAX_INSPECT_BYTES = 1_000_000
# Cuando el payload pasa el tope se mira la cabeza y la cola: meter el secreto al
# final de un archivo grande es la evasion mas barata que existe.
TAIL_BYTES = 100_000
MAX_TOTAL_EXPANDED_CHARS = 4_000_000

_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
MAX_BASE64_RUNS = 25

_TEXT_ZIP_MEMBERS = (".xml", ".txt", ".json", ".md", ".csv", ".yaml", ".yml", ".rels")
MAX_ZIP_MEMBERS = 40

_ZIP_MAGIC = b"PK\x03\x04"
_GZIP_MAGIC = b"\x1f\x8b"

# Comprimir el texto esquiva cualquier escaner de reglas, y no hace falta ser
# malicioso para lograrlo: basta con adjuntar un .gz o un .docx.
MAX_DECOMPRESSED_BYTES = 4_000_000

# Cuantos contenedores embebidos se intentan abrir por payload. Acotado porque la
# firma de gzip son dos bytes y aparece por casualidad en cualquier binario.
MAX_CONTENEDORES = 3

# Un secreto partido con espacios o saltos deja de matchear cualquier regex. La
# vista compacta lo vuelve a unir; va limitada por tamano porque recorre todo.
MAX_COMPACT_INPUT = 200_000
_WHITESPACE = re.compile(r"[\s​ ]+")

BASE64_MAX_DEPTH = 2

# Un hexdump es la forma en que un desarrollador pega un blob binario, y el
# secreto que lleva adentro no lo ve ninguna regla. Se acota igual que base64:
# solo se decodifican corridas largas, y solo si lo que sale es texto.
_HEX_RUN = re.compile(r"(?:[0-9a-fA-F]{2}[\s:]?){16,}")
MAX_HEX_RUNS = 10

# Caracteres invisibles. El de ancho cero es el vector de evasion mas barato que
# existe Y una fuente de falsos negativos accidentales: aparece solo al copiar de
# una pagina web, de un PDF o de Confluence. Nadie tiene que querer evadir nada.
_INVISIBLES = dict.fromkeys(
    [
        0x00AD,  # soft hyphen
        0x200B,  # zero width space
        0x200C,  # zero width non-joiner
        0x200D,  # zero width joiner
        0x200E,  # left-to-right mark
        0x200F,  # right-to-left mark
        0x2060,  # word joiner
        0xFEFF,  # zero width no-break space
    ]
)

# Homoglifos: letras cirilicas y griegas que se dibujan igual que las latinas.
# NFKC no las toca --son letras distintas de verdad, no variantes de forma-- asi
# que hay que mapearlas a mano. La lista es corta a proposito: solo las que se
# ven IDENTICAS en una tipografia comun, que son las que sirven para esconder
# algo. Una que se ve parecida pero distinta no engana a nadie.
_HOMOGLIFOS = str.maketrans(
    {
        # cirilico mayuscula -> latino
        "А": "A", "В": "B", "Е": "E", "К": "K",
        "М": "M", "Н": "H", "О": "O", "Р": "P",
        "С": "C", "Т": "T", "У": "Y", "Х": "X",
        "І": "I", "Ј": "J", "Ѕ": "S",
        # cirilico minuscula
        "а": "a", "е": "e", "о": "o", "р": "p",
        "с": "c", "у": "y", "х": "x", "і": "i",
        "ј": "j", "ѕ": "s",
        # griego
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z",
        "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M",
        "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
        "Υ": "Y", "Χ": "X", "ο": "o", "ρ": "p",
        "ν": "v",
    }
)

# Hasta donde se normaliza. Recorre todo el texto, asi que va acotado igual que
# la vista compacta.
MAX_NORMALIZE_INPUT = 200_000

# Cuantos streams de un PDF se intentan descomprimir.
MAX_PDF_STREAMS = 20
# Los separadores se arman desde sus codigos y no como escapes: escribir
# barras invertidas en una expresion regular a traves de una herramienta de
# edicion es la trampa que documenta ESTADO.md seccion 6.
_TRAS_STREAM = bytes([13, 10, 9, 32])
_PDF_STREAM = re.compile(
    b"stream[" + re.escape(_TRAS_STREAM) + b"]{0,2}(.*?)endstream", re.DOTALL
)


# Un correo suelto en un prompt es una mencion. Quince en el mismo envio son una
# base de clientes, y ninguna regla individual puede notar la diferencia: la
# senal esta en el volumen, no en el dato.
BULK_PII_THRESHOLD = 15
_BULK_PII_RULES = ("email_address", "credit_card", "latam_national_id", "iban")


_ORDEN_SEVERIDAD = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _rank(finding: Finding) -> tuple[int, float, str]:
    return (_ORDEN_SEVERIDAD[finding.severity], -finding.confidence, finding.rule_id)


@dataclass(frozen=True)
class ScanResult:
    findings: list[Finding]
    truncated: bool
    views: int


def _bulk_pii(counts: Counter[str]) -> Finding | None:
    total = sum(counts[rule_id] for rule_id in _BULK_PII_RULES)
    if total >= BULK_PII_THRESHOLD:
        finding = Finding(
            rule_id="bulk_pii_export",
            category="internal_data",
            severity="critical",
            confidence=0.95,
            evidence=f"<pii x{total}>"[:32],
            start=0,
            end=0,
        )
    else:
        finding = None
    return finding


def _decode(payload: bytes) -> str:
    """Decodifica sin confiar en el content-type, que el cliente controla."""

    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = payload.decode("utf-16", errors="replace")
    else:
        # Un texto UTF-16 sin BOM llega lleno de nulos y en UTF-8 queda ilegible,
        # que es justo lo que necesita alguien para esconder una credencial.
        sample = payload[:2000]
        if sample.count(b"\x00") > len(sample) // 4:
            text = payload.decode("utf-16", errors="replace")
        else:
            text = payload.decode("utf-8", errors="replace")
    return text


def _zip_views(payload: bytes) -> list[str]:
    views: list[str] = []
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
        members = [
            name
            for name in archive.namelist()
            if name.lower().endswith(_TEXT_ZIP_MEMBERS)
        ][:MAX_ZIP_MEMBERS]
        for name in members:
            with archive.open(name) as member:
                views.append(_decode(member.read(MAX_INSPECT_BYTES)))
    except (zipfile.BadZipFile, OSError, RuntimeError):
        views = []
    return views


def _gunzip(payload: bytes) -> bytes:
    """Descomprime tolerando lo que venga pegado atras.

    gzip.decompress exige que el stream termine donde termina el buffer, y en un
    multipart siempre hay un boundary despues del archivo.
    """

    try:
        data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(
            payload, MAX_DECOMPRESSED_BYTES
        )
    except zlib.error:
        data = b""
    return data


def _container_views(payload: bytes) -> list[str]:
    """Abre los contenedores que vienen embebidos, no solo el que arranca el body.

    Un archivo casi nunca llega solo: viaja dentro de un multipart, con las
    cabeceras del formulario adelante y el cierre del boundary atras. Buscar la
    firma unicamente en el primer byte deja pasar el gesto mas comun que existe,
    que es arrastrar un .docx a un chat de IA.
    """

    views: list[str] = []

    if _ZIP_MAGIC in payload:
        # zipfile ubica el directorio central desde el final, asi que tolera por
        # si solo tanto lo que viene antes del zip como lo que viene despues.
        views.extend(_zip_views(payload))
        inicio = payload.find(_ZIP_MAGIC)
        if not views and inicio > 0:
            views.extend(_zip_views(payload[inicio:]))

    # El tercer byte de una cabecera gzip es el metodo de compresion, y siempre
    # es deflate. Incluirlo en la busqueda evita perseguir cada par de bytes que
    # coincide por casualidad dentro de un binario.
    desde = 0
    for _ in range(MAX_CONTENEDORES):
        desde = payload.find(_GZIP_MAGIC + b"\x08", desde)
        if desde < 0:
            break
        crudo = _gunzip(payload[desde:])
        if crudo:
            views.append(_decode(crudo))
        desde += len(_GZIP_MAGIC)

    return views


def _base64_views(text: str, depth: int = BASE64_MAX_DEPTH) -> list[str]:
    views: list[str] = []
    for match in _BASE64_RUN.finditer(text):
        if len(views) < MAX_BASE64_RUNS:
            chunk = match.group(0)
            padded = chunk + "=" * (-len(chunk) % 4)
            try:
                decoded = base64.b64decode(padded, validate=True)
            except (binascii.Error, ValueError):
                decoded = b""
            if decoded:
                if decoded.startswith(_GZIP_MAGIC):
                    decoded = _gunzip(decoded)
                view = decoded.decode("utf-8", errors="replace")
                views.append(view)
                # Doble codificacion: base64 de base64 es un clasico y cuesta
                # una pasada mas, no una arquitectura distinta.
                if depth > 1:
                    views.extend(_base64_views(view, depth - 1))
    return views


def sin_tildes(text: str) -> str:
    """El texto sin diacriticos: contrasena por contrasena, cedula por cedula."""

    descompuesto = unicodedata.normalize("NFD", text)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def vista_normalizada(text: str) -> str:
    """El mismo texto con los caracteres que se dibujan igual, unificados.

    Cubre tres cosas que ninguna regla puede ver por su cuenta:

      - **Invisibles.** Un espacio de ancho cero adentro de una llave de AWS la
        vuelve invisible para el patron. Y este es el caso que mas importa de los
        tres, por una razon que no es la obvia: **no requiere un atacante.** Un
        caracter de ancho cero o un guion suave aparecen solos al copiar de una
        pagina web, de un PDF o de Confluence. Asi que es a la vez el vector de
        evasion mas barato Y una fuente de falsos negativos accidentales.
      - **Variantes de forma.** NFKC unifica los anchos completos y los alfabetos
        matematicos, que es como llega el texto pegado de una hoja de calculo o
        de un documento con formato.
      - **Homoglifos.** Una A cirilica y una A latina se dibujan igual y son
        letras distintas de verdad: NFKC no las toca y hay que mapearlas a mano.

    Lo que NO se cubre, y conviene que este escrito para que nadie lo tome por un
    olvido: rot13, el texto invertido, base32, base85 y cualquier otra
    codificacion que alguien aplique **a proposito**. Esa lista no termina nunca,
    y cada vista nueva es una pasada completa de reglas sobre todo el cuerpo --o
    sea, latencia en el camino critico de cada envio. La frontera que se eligio
    es: se cubre lo que aparece solo o por herramientas normales, y se acepta que
    un adversario decidido que codifica adrede queda fuera del alcance de T1. Es
    la misma frontera que tiene cualquier DLP, y decirla es mejor que fingir que
    no existe.
    """

    if len(text) > MAX_NORMALIZE_INPUT:
        resultado = text
    else:
        limpio = text.translate(_INVISIBLES).translate(_HOMOGLIFOS)
        resultado = unicodedata.normalize("NFKC", limpio)
    return resultado


def _hex_views(text: str) -> list[str]:
    """Lo que sale de decodificar las corridas largas de hexadecimal.

    Un hexdump es como un desarrollador pega un blob binario, y el secreto que
    lleva adentro no lo ve ninguna regla. Se acota igual que base64 --solo
    corridas largas, y un tope de cuantas-- y se descarta lo que no sale como
    texto: un binario decodificado es ruido que le cuesta una pasada de reglas a
    cada envio.
    """

    views: list[str] = []
    for match in _HEX_RUN.finditer(text):
        if len(views) >= MAX_HEX_RUNS:
            break
        crudo = re.sub(r"[\s:]", "", match.group(0))
        if len(crudo) % 2:
            crudo = crudo[:-1]
        try:
            datos = bytes.fromhex(crudo)
        except ValueError:
            continue
        # Solo si lo que salio es texto. El umbral es alto a proposito: con uno
        # bajo, cualquier binario entra como vista y se paga la pasada de reglas.
        imprimibles = sum(1 for b in datos if 32 <= b < 127 or b in (9, 10, 13))
        if datos and imprimibles / len(datos) > 0.9:
            views.append(datos.decode("utf-8", errors="replace"))
    return views


def _pdf_views(payload: bytes) -> list[str]:
    """El texto de un PDF, que no es un zip y por eso no lo abria nada.

    El motor abre los .docx y los .xlsx porque son zips, y eso esta bien pensado.
    Un PDF es otra cosa: una estructura con streams comprimidos uno por uno. El
    test que pasaba lo hacia con un PDF de stream sin comprimir, que no es el que
    produce ninguna herramienta real: Word, Google Docs y LaTeX escriben
    FlateDecode, y para todos esos el motor era ciego.
    """

    views: list[str] = []
    if b"%PDF" in payload[:1024]:
        for match in _PDF_STREAM.finditer(payload):
            if len(views) >= MAX_PDF_STREAMS:
                break
            crudo = match.group(1)
            try:
                datos = zlib.decompressobj().decompress(crudo, MAX_DECOMPRESSED_BYTES)
            except zlib.error:
                # Un stream sin comprimir --o comprimido con otro filtro-- se
                # mira tal cual: puede ser el que lleva el texto.
                datos = crudo
            if datos:
                views.append(_decode(datos))
    return views


def _derived_views(text: str) -> list[str]:
    views: list[str] = []

    if "%" in text:
        views.append(unquote_plus(text))

    # JSON escapa los saltos, las comillas y a veces los caracteres ASCII
    # completos. Sin deshacerlo, ni "sk-ant-..." ni password = "..." los ve
    # ninguna regla, porque el prompt viaja dentro de otro JSON.
    if "\\u" in text or "\\n" in text or '\\"' in text:
        views.append(text.replace("\\n", "\n").replace("\\/", "/").encode().decode("unicode_escape", "replace"))

    views.extend(_base64_views(text))
    views.extend(_hex_views(text))

    # La normalizacion va DESPUES de las vistas derivadas y sobre cada una de
    # ellas, no solo sobre el texto original, y esa es la parte que importa: el
    # cuerpo llega como JSON con ensure_ascii, asi que un espacio de ancho cero
    # viaja escrito como los seis caracteres "\\u200b" y solo se vuelve invisible
    # DESPUES de deshacer el escape. Normalizando unicamente el original, la
    # evasion pasaba igual --que es exactamente lo que medi.
    normalizadas = [
        normalizada
        for vista in [text, *views]
        if (normalizada := vista_normalizada(vista)) != vista
    ]
    views.extend(normalizadas)

    if len(text) <= MAX_COMPACT_INPUT:
        # La compacta se calcula sobre las normalizadas tambien: un secreto
        # partido con espacios Y con un homoglifo adentro necesita las dos.
        for vista in [text, *normalizadas]:
            compact = _WHITESPACE.sub("", vista)
            if compact != vista:
                views.append(compact)

    return views


def texto_para_inyeccion(body: bytes | None) -> str:
    """El texto que la persona (o el agente) escribio, listo para inspeccionar.

    Reusa el mismo decodificado que el resto del archivo en vez de una copia:
    una inyeccion escondida en un cuerpo gzipeado o en un JSON escapado tiene
    que verse igual que una en texto plano.
    """

    if not body:
        texto = ""
    else:
        crudo = body[:MAX_INSPECT_BYTES]
        if crudo.startswith(_GZIP_MAGIC):
            crudo = _gunzip(crudo) or crudo
        principal = _decode(crudo)
        texto = extract_prompt(principal) or principal
    return texto


def texto_de_respuesta(cuerpo: bytes | None) -> str:
    """El texto que escribio el modelo, sin el sobre JSON que lo lleva.

    Hace falta extraerlo: el texto de una respuesta empieza justo despues de una
    comilla (`"text":"Ignora las...`), y la regla de inyeccion exige que la orden
    ABRA una oracion. Sin separar los valores del JSON, una orden puesta al
    principio de la respuesta no se veia.

    Aflojar la regla para que una comilla cuente como inicio seria peor: volveria
    a marcar a cualquiera que cite una inyeccion entre comillas para explicarla,
    que es lo que hace toda la documentacion de seguridad. Se extrae el texto y
    la regla se queda como esta.

    Cubre las tres formas en que contesta una API de modelos: JSON, streaming
    por eventos (`data: {...}`) y texto plano.
    """

    if not cuerpo:
        return ""

    crudo = cuerpo[:MAX_INSPECT_BYTES].decode("utf-8", "replace")
    partes: list[str] = []

    for linea in crudo.splitlines():
        limpia = linea.strip()
        if limpia.startswith("data:"):
            limpia = limpia[5:].strip()
        if limpia and limpia[0] in "{[":
            try:
                partes.extend(_cadenas(json.loads(limpia)))
                continue
            except ValueError:
                pass
        partes.append(limpia)

    return "\n".join(partes) if partes else crudo


def _cadenas(dato) -> list[str]:
    """Todas las cadenas de una estructura JSON, en orden."""

    encontradas: list[str] = []
    if isinstance(dato, str):
        encontradas.append(dato)
    else:
        if isinstance(dato, dict):
            for valor in dato.values():
                encontradas.extend(_cadenas(valor))
        else:
            if isinstance(dato, list):
                for valor in dato:
                    encontradas.extend(_cadenas(valor))
    return encontradas


def scan_payload(
    body: bytes | None, query: str = "", terminos: dict[str, str] | None = None
) -> ScanResult:
    """Escanea un request completo, incluidas sus formas ofuscadas.

    Devuelve hallazgos deduplicados: el mismo secreto visto en el texto plano y
    en su version base64 es un solo incidente, no dos.
    """

    truncated = False
    payload = body or b""
    if len(payload) > MAX_INSPECT_BYTES:
        payload = payload[:MAX_INSPECT_BYTES] + payload[-TAIL_BYTES:]
        truncated = True

    views: list[str] = []
    principal = ""
    if query:
        views.append(query)
        views.append(unquote_plus(query))

    if payload:
        if payload.startswith(_GZIP_MAGIC):
            payload = _gunzip(payload) or payload
        views.extend(_container_views(payload))
        views.extend(_pdf_views(payload))
        principal = _decode(payload)
        views.append(principal)
        views.extend(_derived_views(principal))

        # El pantallazo. Va al final y detras de una bandera porque es la unica
        # vista que cuesta SEGUNDOS y no milisegundos (ver detect/ocr.py), asi
        # que todo lo de arriba ya se resolvio antes de considerar pagarla. La
        # extraccion de las imagenes es barata y siempre corre; lo que esta
        # apagado por defecto es leerlas.
        if ocr.habilitado():
            imagenes = extraer_imagenes(payload, principal)
            if imagenes:
                views.extend(ocr.vistas(imagenes))

    # El espanol de verdad lleva tildes y enes. Las reglas estan escritas sin
    # ellas, asi que una regla veia "la contrasena del servidor" y NINGUNA veia
    # "la contraseña", que es como se escribe la palabra. No era una evasion:
    # era la forma normal de escribirla.
    #
    # Va aca y no dentro de _derived_views porque el prompt viaja dentro de un
    # JSON que escapa la ene como ñ: el texto principal es ASCII y la ene
    # solo aparece en la vista desescapada. Aplicarlo sobre TODAS las vistas es
    # lo unico que la alcanza, y de paso una regla nueva hereda la cobertura sin
    # que su autor tenga que acordarse.
    views.extend(
        plano
        for vista in list(views)
        if not vista.isascii() and (plano := sin_tildes(vista)) != vista
    )

    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    # La vista sin tildes es, por construccion, casi una copia de su original:
    # sin esto cada fuga con una ene se reportaria dos veces. Se comparan por
    # posicion porque quitar un diacritico no mueve los caracteres de lugar.
    posiciones: set[tuple[str, int]] = set()
    counts: Counter[str] = Counter()
    budget = MAX_TOTAL_EXPANDED_CHARS
    scanned = 0
    for view in views:
        if budget > 0:
            budget -= len(view)
            scanned += 1
            # El tope de la vista incluye la cola: recortar aca de nuevo dejaria
            # afuera justo el pedazo que se conservo para no perder el final.
            recorte = view[: MAX_INSPECT_BYTES + TAIL_BYTES]
            view_findings = scan(recorte)
            # El diccionario de la empresa se mira sobre las mismas vistas que
            # las reglas: si comprimir el cuerpo o pasarlo por base64 alcanzara
            # para esconder el nombre de un cliente, la lista no serviria.
            if terminos:
                view_findings = view_findings + diccionario.buscar(recorte, terminos)
            for rule_id, total in Counter(f.rule_id for f in view_findings).items():
                # Se toma el maximo por vista y no la suma: el mismo export visto
                # en texto plano y en base64 no son dos fugas distintas.
                counts[rule_id] = max(counts[rule_id], total)
            for finding in view_findings:
                key = (finding.rule_id, finding.evidence)
                posicion = (finding.rule_id, finding.start)
                if key not in seen and posicion not in posiciones:
                    seen.add(key)
                    posiciones.add(posicion)
                    findings.append(finding)

    # El archivo puede ser critico por lo que es, no por lo que dice: un
    # volcado binario no tiene ni una palabra que una regla de texto encuentre.
    for hallazgo in scan_files(payload, principal):
        clave = (hallazgo.rule_id, hallazgo.evidence)
        if clave not in seen:
            seen.add(clave)
            findings.append(hallazgo)

    bulk = _bulk_pii(counts)
    if bulk is not None:
        findings.append(bulk)

    # T2 solo entra cuando T1 se quedo sin nada que decir. Si ya hay una
    # credencial detectada, gastar 150 ms mas no cambia la decision ni la
    # leccion; y si T1 vio algo, lo vio con certeza y sin adivinar.
    if not findings and principal:
        # Al modelo se le da lo que escribio la persona, no el sobre que lo
        # lleva. Si la forma del request no se reconoce se mira todo: un
        # servicio que nadie clasifico todavia tampoco tiene una forma conocida,
        # y recortar ahi seria recortar justo el caso peligroso.
        findings.extend(scan_model(extract_prompt(principal) or principal))

    # Se reordena al final para que el primero sea el hallazgo mas especifico, no
    # el ultimo que se agrego. De ese primero sale la leccion que ve la persona,
    # y "es una llave de AWS" ensena mucho mas que "es un archivo critico".
    findings.sort(key=_rank)

    return ScanResult(findings=findings, truncated=truncated, views=scanned)
