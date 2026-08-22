from __future__ import annotations

import base64
import binascii
import gzip
import io
import re
import zipfile
from dataclasses import dataclass
from urllib.parse import unquote_plus

from .engine import scan
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

# Un secreto partido con espacios o saltos deja de matchear cualquier regex. La
# vista compacta lo vuelve a unir; va limitada por tamano porque recorre todo.
MAX_COMPACT_INPUT = 200_000
_WHITESPACE = re.compile(r"[\s​ ]+")

BASE64_MAX_DEPTH = 2


@dataclass(frozen=True)
class ScanResult:
    findings: list[Finding]
    truncated: bool
    views: int


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
    try:
        data = gzip.decompress(payload)[:MAX_DECOMPRESSED_BYTES]
    except (OSError, EOFError):
        data = b""
    return data


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


def _derived_views(text: str) -> list[str]:
    views: list[str] = []

    if "%" in text:
        views.append(unquote_plus(text))

    # JSON escapa los saltos y a veces los caracteres ASCII completos; sin
    # deshacerlo, "sk-ant-..." no lo ve ninguna regla.
    if "\\u" in text or "\\n" in text:
        views.append(text.replace("\\n", "\n").replace("\\/", "/").encode().decode("unicode_escape", "replace"))

    views.extend(_base64_views(text))

    if len(text) <= MAX_COMPACT_INPUT:
        compact = _WHITESPACE.sub("", text)
        if compact != text:
            views.append(compact)

    return views


def scan_payload(body: bytes | None, query: str = "") -> ScanResult:
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
    if query:
        views.append(query)
        views.append(unquote_plus(query))

    if payload:
        if payload.startswith(_GZIP_MAGIC):
            payload = _gunzip(payload) or payload
        if payload.startswith(_ZIP_MAGIC):
            views.extend(_zip_views(payload))
        primary = _decode(payload)
        views.append(primary)
        views.extend(_derived_views(primary))

    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    budget = MAX_TOTAL_EXPANDED_CHARS
    scanned = 0
    for view in views:
        if budget > 0:
            budget -= len(view)
            scanned += 1
            # El tope de la vista incluye la cola: recortar aca de nuevo dejaria
            # afuera justo el pedazo que se conservo para no perder el final.
            for finding in scan(view[: MAX_INSPECT_BYTES + TAIL_BYTES]):
                key = (finding.rule_id, finding.evidence)
                if key not in seen:
                    seen.add(key)
                    findings.append(finding)

    return ScanResult(findings=findings, truncated=truncated, views=scanned)
