from __future__ import annotations

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


def _findings_for_rule(rule: Rule, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for match in rule.pattern.finditer(text):
        value = match.group(rule.group)
        accepted = bool(value) and (rule.validator is None or rule.validator(value))
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


def scan(text: str, rules: tuple[Rule, ...] = RULES) -> list[Finding]:
    """Hallazgos del texto, del mas severo al menos severo.

    El texto original no queda referenciado en el resultado: los Finding solo
    llevan evidencia redactada. Por defecto corren las reglas de fabrica; la
    politica de la empresa puede pasar su propio conjunto (detect/ruleset.py).
    """

    if not text:
        result: list[Finding] = []
    else:
        findings: list[Finding] = []
        for rule in rules:
            findings.extend(_findings_for_rule(rule, text))
        result = sorted(_drop_overlapping(findings), key=_rank)
    return result


def highest_severity(findings: list[Finding]) -> Severity | None:
    if findings:
        severity: Severity | None = findings[0].severity
    else:
        severity = None
    return severity
