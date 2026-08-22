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


@dataclass(frozen=True)
class Finding:
    rule_id: str
    category: Category
    severity: Severity
    confidence: float
    evidence: str
    start: int
    end: int

    def __post_init__(self) -> None:
        # La evidencia es el unico campo que sale del equipo. Si algun dia una
        # regla emite mas de la cuenta, que reviente aca y no en produccion.
        if len(self.evidence) > EVIDENCE_MAX_LEN:
            raise ValueError(
                f"evidencia de {self.rule_id} excede {EVIDENCE_MAX_LEN} caracteres"
            )
