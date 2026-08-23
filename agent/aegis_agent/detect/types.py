from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Estos literales viajan tal cual en el evento de incidente: si cambian aca,
# cambia el contrato con el backend (docs/spec/contrato-de-datos.md).
Category = Literal["secret", "pii", "internal_data", "policy"]
Severity = Literal["critical", "high", "medium", "low"]
Engine = Literal["t1_rules", "t2_model"]

EVIDENCE_MAX_LEN = 32
EVIDENCE_VISIBLE_PREFIX = 4

# De donde salio el texto en el que se encontro el hallazgo.
#
# No es cosmetico: decide cuanta autoridad tiene. El texto de un OCR es
# aproximado -medido en detect/ocr.py, `Verano2026Bogota` salio como
# `Verano2o26Bogota` y una llave de AWS no se leyo a 900 px y si a 1800-, asi
# que un hallazgo leido de una imagen es tan probabilistico como uno del modelo
# local y no puede cortar un envio con la misma autoridad que una llave con
# formato reconocido. Ver policy.ocr_action.
ORIGEN_TEXTO = "texto"
ORIGEN_IMAGEN = "imagen"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    category: Category
    severity: Severity
    confidence: float
    evidence: str
    start: int
    end: int
    # Va al final y con default para que las decenas de sitios que construyen un
    # Finding no tengan que nombrarlo: lo normal es que el texto sea texto.
    origen: str = ORIGEN_TEXTO

    def __post_init__(self) -> None:
        # La evidencia es el unico campo que sale del equipo. Si algun dia una
        # regla emite mas de la cuenta, que reviente aca y no en produccion.
        if len(self.evidence) > EVIDENCE_MAX_LEN:
            raise ValueError(
                f"evidencia de {self.rule_id} excede {EVIDENCE_MAX_LEN} caracteres"
            )
