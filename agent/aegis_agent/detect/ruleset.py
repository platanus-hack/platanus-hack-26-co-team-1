"""Compila la politica de la empresa en el conjunto de reglas que corre el motor.

Las reglas de fabrica (rules.RULES) son un tuple fijo; lo que la empresa puede
tocar -- apagar una regla, prohibir un termino, agregar una regex propia --
vive en la politica como texto. Este modulo junta las dos cosas una sola vez
por politica: compilar regexes en cada request seria pagar el mismo costo
miles de veces, asi que el resultado se cachea por identidad del objeto
Policy, que solo cambia cuando el hot-reload trae una politica distinta.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .model import ETIQUETAS_POR_DEFECTO, UMBRAL_POR_DEFECTO
from .rules import RULES, Rule

if TYPE_CHECKING:  # pragma: no cover - solo para tipos, evita el ciclo de imports
    from ..policy import Policy


@dataclass(frozen=True)
class RuleSet:
    """Lo que el motor necesita saber de la politica, ya compilado."""

    # Las reglas activas: fabrica menos apagadas, mas terminos y regex propias.
    rules: tuple[Rule, ...]
    # Tambien suprime los hallazgos sinteticos que no nacen de una Rule
    # (bulk_pii_export, archivo_critico...): se filtran por id en payload.py.
    disabled: frozenset[str]
    model_labels: tuple[str, ...]
    model_threshold: float
    # Ids de reglas personalizadas cuya regex no compilo. No se lanzan: una
    # politica editada a mano no puede dejar a la empresa sin proteccion.
    descartadas: tuple[str, ...] = ()


RULESET_POR_DEFECTO = RuleSet(
    rules=RULES,
    disabled=frozenset(),
    model_labels=ETIQUETAS_POR_DEFECTO,
    model_threshold=UMBRAL_POR_DEFECTO,
)

# Cache de una sola entrada, por identidad. Alcanza porque el addon tiene una
# unica referencia de politica viva; comparar con "is" evita el costo de un
# __eq__ campo por campo en cada request.
_cache_lock = threading.Lock()
_cache: tuple[Any, RuleSet] | None = None


def _regla_de_terminos(terminos: tuple[str, ...], categoria: str) -> Rule:
    """Una sola regla para todos los terminos prohibidos.

    Cada termino se escapa y se envuelve en lookarounds cuando empieza o
    termina en caracter de palabra: "sol" no puede matchear "solucion". Se
    usan lookarounds y no \\b a proposito: escribir \\b a traves de las
    herramientas de edicion ya grabo una vez un byte de retroceso literal
    (docs/ESTADO.md, seccion 6).
    """

    partes = []
    for termino in terminos:
        escapado = re.escape(termino)
        if re.match(r"\w", termino):
            escapado = "(?<!\\w)" + escapado
        if re.search(r"\w$", termino):
            escapado = escapado + "(?!\\w)"
        partes.append(escapado)
    return Rule(
        id="termino_prohibido",
        category=categoria,  # type: ignore[arg-type]
        severity="high",
        confidence=0.9,
        pattern=re.compile("|".join(partes), re.IGNORECASE),
        description="Termino que la empresa prohibio mencionar",
        # El termino ES el secreto: la evidencia dice el tipo, nunca el valor.
        redact_as="type",
        kind="termino prohibido",
    )


def _compilar(policy: "Policy") -> RuleSet:
    # Hay DOS formas de apagar una regla y las dos llegaron por caminos
    # distintos: `disabled_rules` (una lista de ids) y `rule_actions[id]="off"`
    # (que ademas sabe decir block/warn). Se unen aca y en ningun otro lado: dos
    # maneras de escribirlo en la politica, una sola de decidirlo en el motor.
    #
    # Los terminos NO se unifican, y es a proposito: `company_terms` produce
    # hallazgos `empresa_*` con su propia perilla (company_terms_action) y
    # `forbidden_terms` produce `termino_prohibido`, que decide por categoria.
    # Fundirlos cambiaria el id y se llevaria puesta una de las dos perillas.
    apagadas = frozenset(policy.disabled_rules) | {
        rule_id
        for rule_id, accion in policy.rule_actions.items()
        if accion == "off"
    }
    activas = [r for r in RULES if r.id not in apagadas]

    terminos = tuple(t for t in policy.forbidden_terms if t.strip())
    if terminos and "termino_prohibido" not in apagadas:
        activas.append(_regla_de_terminos(terminos, policy.forbidden_terms_category))

    descartadas: list[str] = []
    for propia in policy.custom_rules:
        if propia.id in apagadas:
            continue
        # Una regex con backtracking catastrofico puede frenar el proxy: re de
        # stdlib no tiene timeout. El input esta acotado por los limites de
        # vista del payload, pero es una limitacion conocida.
        try:
            patron = re.compile(propia.pattern)
        except re.error:
            descartadas.append(propia.id)
            continue
        activas.append(
            Rule(
                id=propia.id,
                category=propia.category,  # type: ignore[arg-type]
                severity=propia.severity,  # type: ignore[arg-type]
                confidence=0.85,
                pattern=patron,
                description="Regla definida por la empresa",
            )
        )

    return RuleSet(
        rules=tuple(activas),
        disabled=apagadas,
        model_labels=tuple(policy.model_labels),
        model_threshold=policy.model_threshold,
        descartadas=tuple(descartadas),
    )


def ruleset_de(policy: "Policy") -> RuleSet:
    """El conjunto compilado para esta politica, cacheado mientras sea la misma."""

    global _cache
    with _cache_lock:
        if _cache is not None and _cache[0] is policy:
            return _cache[1]
    conjunto = _compilar(policy)
    with _cache_lock:
        _cache = (policy, conjunto)
    return conjunto
