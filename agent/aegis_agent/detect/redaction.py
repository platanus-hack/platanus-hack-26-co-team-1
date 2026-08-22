from __future__ import annotations

from .types import EVIDENCE_MAX_LEN, EVIDENCE_VISIBLE_PREFIX

MASK_CHAR = "*"


def redact(value: str) -> str:
    """Deja el prefijo visible y enmascara el resto, con tope de longitud.

    El tope no es cosmetico: sin el, la evidencia filtraria la longitud exacta
    del secreto original.
    """

    visible = value[:EVIDENCE_VISIBLE_PREFIX]
    masked_len = max(0, min(len(value) - len(visible), EVIDENCE_MAX_LEN - len(visible)))
    return visible + MASK_CHAR * masked_len


def redact_fully(kind: str) -> str:
    # Para PII no se muestra ni el prefijo: un admin no necesita ver medio correo.
    return f"<{kind}>"[:EVIDENCE_MAX_LEN]
