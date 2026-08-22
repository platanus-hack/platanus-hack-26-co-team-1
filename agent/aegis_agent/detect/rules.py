from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .entropy import looks_random, luhn_valid
from .types import Category, Severity


@dataclass(frozen=True)
class Rule:
    id: str
    category: Category
    severity: Severity
    confidence: float
    pattern: re.Pattern[str]
    description: str
    # Grupo que contiene el valor sensible: 0 para las reglas de formato, 1 para
    # las genericas, donde el match incluye tambien el nombre de la variable.
    group: int = 0
    # Devolver False descarta el match. Es lo que separa un numero de tarjeta de
    # cualquier secuencia de 16 digitos.
    validator: Callable[[str], bool] | None = None
    redact_as: str = "mask"
    kind: str = ""


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


RULES: tuple[Rule, ...] = (
    Rule(
        id="aws_access_key_id",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA)[0-9A-Z]{16}\b"),
        description="Identificador de llave de acceso de AWS",
    ),
    Rule(
        id="anthropic_api_key",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
        description="API key de Anthropic",
    ),
    Rule(
        id="openai_api_key",
        category="secret",
        severity="critical",
        confidence=0.98,
        # El lookahead evita que esta regla se coma tambien las de Anthropic.
        pattern=_compile(r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{20,}"),
        description="API key de OpenAI",
    ),
    Rule(
        id="github_token",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22,})\b"),
        description="Token de acceso de GitHub",
    ),
    Rule(
        id="google_api_key",
        category="secret",
        severity="critical",
        confidence=0.97,
        pattern=_compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
        description="API key de Google",
    ),
    Rule(
        id="slack_token",
        category="secret",
        severity="high",
        confidence=0.97,
        pattern=_compile(r"\bxox[baprs]-[0-9A-Za-z\-]{10,}"),
        description="Token de Slack",
    ),
    Rule(
        id="stripe_secret_key",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b"),
        description="Llave secreta de Stripe en produccion",
    ),
    Rule(
        id="private_key_block",
        category="secret",
        severity="critical",
        confidence=1.0,
        pattern=_compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----"
        ),
        description="Bloque de llave privada",
    ),
    Rule(
        id="jwt",
        category="secret",
        severity="high",
        confidence=0.9,
        pattern=_compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
        description="JSON Web Token",
    ),
    Rule(
        id="db_connection_string",
        category="secret",
        severity="critical",
        confidence=0.98,
        pattern=_compile(
            r"\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://"
            r"[^\s:@/]+:[^\s:@/]+@[^\s/]+"
        ),
        description="Cadena de conexion a base de datos con credenciales",
    ),
    Rule(
        id="generic_secret_assignment",
        category="secret",
        severity="high",
        confidence=0.75,
        pattern=_compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|pwd|credential)s?\b"
            r"\s*[:=]\s*[\"']?([^\s\"']{12,})"
        ),
        description="Asignacion de credencial con valor de alta entropia",
        group=1,
        validator=looks_random,
    ),
    Rule(
        id="credit_card",
        category="pii",
        severity="high",
        confidence=0.95,
        pattern=_compile(r"\b(?:\d[ -]?){13,19}\b"),
        description="Numero de tarjeta que pasa la validacion de Luhn",
        validator=luhn_valid,
        redact_as="type",
        kind="credit_card",
    ),
    Rule(
        id="email_address",
        category="pii",
        severity="medium",
        confidence=0.9,
        pattern=_compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
        description="Direccion de correo electronico",
        redact_as="type",
        kind="email",
    ),
)

RULES_BY_ID = {rule.id: rule for rule in RULES}
