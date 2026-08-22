from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Classification = Literal[
    "ai_approved", "ai_unapproved", "ai_unknown", "non_ai", "passthrough"
]
Action = Literal["allow", "warn", "block_destination", "block_content"]

# Lista semilla. En produccion esto es cache local alimentado por la base
# colaborativa; aca vive en codigo para que el agente arranque sin backend.
AI_DOMAINS: frozenset[str] = frozenset(
    {
        "chatgpt.com",
        "chat.openai.com",
        "api.openai.com",
        "claude.ai",
        "api.anthropic.com",
        "gemini.google.com",
        "aistudio.google.com",
        "notebooklm.google.com",
        "copilot.microsoft.com",
        "chat.deepseek.com",
        "api.deepseek.com",
        "perplexity.ai",
        "poe.com",
        "character.ai",
        "chat.mistral.ai",
        "grok.com",
        "x.ai",
        "huggingface.co",
        "novaai.local",
        "asistente-ia.co",
    }
)

# Dominios que no se descifran nunca, ni para inspeccionar. Ver ADR 0003.
PASSTHROUGH_DOMAINS: frozenset[str] = frozenset(
    {
        "bancolombia.com",
        "davivienda.com",
        "bbva.com.co",
        "gov.co",
        "sura.co",
        "windowsupdate.com",
        "microsoft.com",
        "mozilla.org",
    }
)


@dataclass(frozen=True)
class Policy:
    """Politica de la empresa. En produccion llega del backend y se cachea en disco."""

    tenant_id: str = "acme"
    approved_ai: frozenset[str] = field(default_factory=lambda: frozenset({"claude.ai", "api.anthropic.com"}))
    # Que hacer con un dominio que todavia no esta clasificado. Bloquear es mas
    # seguro; para la demo se advierte, que es lo que pediria una empresa real
    # antes de frenarle el trabajo a la gente.
    unknown_domain_action: Action = "warn"
    block_categories: frozenset[str] = field(default_factory=lambda: frozenset({"secret"}))
    warn_categories: frozenset[str] = field(default_factory=lambda: frozenset({"pii", "internal_data"}))


# Un dominio que nadie clasifico todavia igual se delata por la forma del
# request. Es lo unico que cubre el shadow AI del que la lista negra aun no se
# entero, que es justamente el caso peligroso.
AI_PATH_HINTS: tuple[str, ...] = (
    "/chat",
    "/completion",
    "/v1/messages",
    "/generate",
    "/ask",
    "/prompt",
    "/conversation",
    "/inference",
    "/predict",
    "/assistant",
)

AI_BODY_HINTS: tuple[str, ...] = (
    '"messages"',
    '"prompt"',
    '"model"',
    '"temperature"',
    '"max_tokens"',
    '"system"',
    '"stream"',
)

MIN_BODY_HINTS = 2


def looks_like_ai_api(path: str, text: str) -> bool:
    lowered = path.lower()
    if any(hint in lowered for hint in AI_PATH_HINTS):
        result = True
    else:
        sample = text[:4000]
        hits = sum(1 for hint in AI_BODY_HINTS if hint in sample)
        result = hits >= MIN_BODY_HINTS
    return result


def _matches(host: str, domains: frozenset[str]) -> bool:
    host = host.lower().strip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def classify(host: str, policy: Policy) -> Classification:
    if _matches(host, PASSTHROUGH_DOMAINS):
        classification: Classification = "passthrough"
    else:
        if _matches(host, policy.approved_ai):
            classification = "ai_approved"
        else:
            if _matches(host, AI_DOMAINS):
                classification = "ai_unapproved"
            else:
                classification = "non_ai"
    return classification


def decide(classification: Classification, categories: set[str], policy: Policy) -> Action:
    """Cruza el destino con lo que se encontro en el contenido.

    El orden importa: el destino manda. Un dominio de IA no aprobada se corta
    aunque el contenido venga limpio, porque el problema ahi es el shadow AI, no
    el dato. Y en una IA aprobada no se corta el destino nunca: se corta el dato,
    que es lo que permite que la gente siga trabajando con la herramienta.
    """

    if classification in ("passthrough", "non_ai"):
        action: Action = "allow"
    else:
        if classification == "ai_unapproved":
            action = "block_destination"
        else:
            if categories & policy.block_categories:
                action = "block_content"
            else:
                if categories & policy.warn_categories:
                    action = "warn"
                else:
                    action = "allow"
    return action
