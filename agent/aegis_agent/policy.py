from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Classification = Literal[
    "ai_approved", "ai_unapproved", "ai_unknown", "non_ai", "passthrough"
]
Action = Literal["allow", "warn", "block_destination", "block_content"]

from .catalog import AI_DOMAINS  # noqa: E402  (catalogo semilla)

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
    block_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"secret", "internal_data"})
    )
    warn_categories: frozenset[str] = field(default_factory=lambda: frozenset({"pii"}))


# Un dominio que nadie clasifico todavia igual se delata por la forma del
# request. Es lo unico que cubre el shadow AI del que la lista negra aun no se
# entero, que es justamente el caso peligroso.
AI_PATH_HINTS: tuple[str, ...] = (
    "/chat",
    "/completion",
    "/complete",
    "/v1/messages",
    "/generate",
    ":generate",
    "/ask",
    "/prompt",
    "/conversation",
    "/inference",
    "/predict",
    "/assistant",
    "/embedding",
    "/transcri",
    "/converse",
    "/invocations",
    "/responses",
    "/agent",
    # El mercado hispanohablante nombra sus endpoints en espanol, y una lista
    # armada solo con nombres en ingles no ve el asistente interno de nadie.
    "/asistente",
    "/pregunta",
    "/consulta",
    "/resumen",
    "/resumir",
    "/traducir",
)

# Hay claves que solo aparecen en un request a un modelo y claves que aparecen en
# cualquier API. Pesarlas distinto es lo que separa detectar un asistente nuevo
# de bloquear el sistema de facturacion.
STRONG_BODY_HINTS: tuple[str, ...] = (
    '"messages"',
    '"prompt"',
    '"inputs"',
    '"contents"',
    '"anthropic_version"',
    '"max_tokens"',
    '"max_output_tokens"',
)

WEAK_BODY_HINTS: tuple[str, ...] = (
    '"model"',
    '"temperature"',
    '"stream"',
    '"top_p"',
    '"system"',
    '"completion"',
    '"parameters"',
)

HINT_THRESHOLD = 2
BODY_SAMPLE_CHARS = 4000


def looks_like_ai_api(path: str, text: str) -> bool:
    lowered = path.lower()
    if any(hint in lowered for hint in AI_PATH_HINTS):
        result = True
    else:
        sample = text[:BODY_SAMPLE_CHARS]
        score = sum(2 for hint in STRONG_BODY_HINTS if hint in sample)
        score += sum(1 for hint in WEAK_BODY_HINTS if hint in sample)
        result = score >= HINT_THRESHOLD
    return result


def _match_length(host: str, domains: frozenset[str]) -> int:
    """Longitud del dominio mas especifico que matchea, o 0 si ninguno.

    Se compara por especificidad y no por orden de lista porque las listas se
    solapan: microsoft.com esta en passthrough y copilot.microsoft.com es una IA.
    Con un simple "primero passthrough", Copilot pasaba libre.
    """

    normalized = host.lower().strip(".")
    lengths = [
        len(domain)
        for domain in domains
        if normalized == domain or normalized.endswith("." + domain)
    ]
    return max(lengths) if lengths else 0


def classify(host: str, policy: Policy) -> Classification:
    approved = _match_length(host, policy.approved_ai)
    catalogued = _match_length(host, AI_DOMAINS)
    exempt = _match_length(host, PASSTHROUGH_DOMAINS)

    if approved >= max(catalogued, exempt) and approved > 0:
        classification: Classification = "ai_approved"
    else:
        if catalogued >= exempt and catalogued > 0:
            classification = "ai_unapproved"
        else:
            if exempt > 0:
                classification = "passthrough"
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
