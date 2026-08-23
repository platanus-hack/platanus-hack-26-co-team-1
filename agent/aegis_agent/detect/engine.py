from __future__ import annotations

from .placeholders import es_placeholder
from .redaction import redact, redact_fully
from .rules import RULES, Rule
from .types import Finding, Severity

_SEVERITY_ORDER: dict[Severity, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _evidence_for(rule: Rule, value: str) -> str:
    if rule.redact_as == "type":
        evidence = redact_fully(rule.kind or rule.category)
    else:
        evidence = redact(value)
    return evidence


def _aceptado(rule: Rule, value: str, text: str, start: int, end: int) -> bool:
    """Los tres filtros que puede tener que pasar un match, del mas barato al mas caro.

    El de placeholder se aplica aca y no como validador de cada regla porque las
    reglas de FORMATO no tienen validador --a una llave de OpenAI le alcanzaba su
    prefijo-- y es exactamente ahi donde entro el falso positivo medido:
    ``sk-proj-XXXXXXXXXXXXXXXXXXXX`` cortaba el envio. Poniendolo en el motor,
    ninguna regla de ``secret`` que se agregue manana se olvida de pasarlo.
    """

    if not value:
        aceptado = False
    elif rule.validator is not None and not rule.validator(value):
        aceptado = False
    elif rule.category == "secret" and es_placeholder(value):
        aceptado = False
    elif rule.context_validator is not None and not rule.context_validator(
        text, start, end
    ):
        aceptado = False
    else:
        aceptado = True
    return aceptado


def _findings_for_rule(rule: Rule, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in rule.pattern.finditer(text):
        value = match.group(rule.group)
        accepted = _aceptado(
            rule, value, text, match.start(rule.group), match.end(rule.group)
        )
        if accepted:
            findings.append(
                Finding(
                    rule_id=rule.id,
                    category=rule.category,
                    severity=rule.severity,
                    confidence=rule.confidence,
                    evidence=_evidence_for(rule, value),
                    start=match.start(rule.group),
                    end=match.end(rule.group),
                )
            )
    return findings


def _rank(finding: Finding) -> tuple[int, float, int]:
    return (_SEVERITY_ORDER[finding.severity], -finding.confidence, finding.start)


def _drop_overlapping(findings: list[Finding]) -> list[Finding]:
    """Se queda con el hallazgo mas severo cuando dos reglas pisan el mismo texto.

    Una llave de OpenAI dentro de ``api_key = sk-...`` la ven dos reglas; sin
    esto el incidente se reporta con el doble de hallazgos de los que hubo.
    """

    kept: list[Finding] = []
    for finding in sorted(findings, key=_rank):
        overlaps = any(
            finding.start < other.end and other.start < finding.end for other in kept
        )
        if not overlaps:
            kept.append(finding)
    return kept


def scan(text: str) -> list[Finding]:
    """Hallazgos del texto, del mas severo al menos severo.

    El texto original no queda referenciado en el resultado: los Finding solo
    llevan evidencia redactada.
    """

    if not text:
        result: list[Finding] = []
    else:
        findings: list[Finding] = []
        for rule in RULES:
            findings.extend(_findings_for_rule(rule, text))
        result = sorted(_drop_overlapping(findings), key=_rank)
    return result


def highest_severity(findings: list[Finding]) -> Severity | None:
    if findings:
        severity: Severity | None = findings[0].severity
    else:
        severity = None
    return severity
