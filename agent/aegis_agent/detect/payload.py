from __future__ import annotations

import base64
import binascii
import gzip
import io
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from urllib.parse import unquote_plus

from .engine import scan
from .files import scan_files
from .model import scan_model
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

    # JSON escapa los saltos, las comillas y a veces los caracteres ASCII
    # completos. Sin deshacerlo, ni "sk-ant-..." ni password = "..." los ve
    # ninguna regla, porque el prompt viaja dentro de otro JSON.
    if "\\u" in text or "\\n" in text or '\\"' in text:
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
    principal = ""
    if query:
        views.append(query)
        views.append(unquote_plus(query))

    if payload:
        if payload.startswith(_GZIP_MAGIC):
            payload = _gunzip(payload) or payload
        if payload.startswith(_ZIP_MAGIC):
            views.extend(_zip_views(payload))
        principal = _decode(payload)
        views.append(principal)
        views.extend(_derived_views(principal))

    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    budget = MAX_TOTAL_EXPANDED_CHARS
    scanned = 0
    for view in views:
        if budget > 0:
            budget -= len(view)
            scanned += 1
            # El tope de la vista incluye la cola: recortar aca de nuevo dejaria
            # afuera justo el pedazo que se conservo para no perder el final.
            view_findings = scan(view[: MAX_INSPECT_BYTES + TAIL_BYTES])
            for rule_id, total in Counter(f.rule_id for f in view_findings).items():
                # Se toma el maximo por vista y no la suma: el mismo export visto
                # en texto plano y en base64 no son dos fugas distintas.
                counts[rule_id] = max(counts[rule_id], total)
            for finding in view_findings:
                key = (finding.rule_id, finding.evidence)
                if key not in seen:
                    seen.add(key)
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
        findings.extend(scan_model(principal))

    # Se reordena al final para que el primero sea el hallazgo mas especifico, no
    # el ultimo que se agrego. De ese primero sale la leccion que ve la persona,
    # y "es una llave de AWS" ensena mucho mas que "es un archivo critico".
    findings.sort(key=_rank)

    return ScanResult(findings=findings, truncated=truncated, views=scanned)
