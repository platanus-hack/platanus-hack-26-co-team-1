from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

Classification = Literal[
    "ai_approved", "ai_unapproved", "ai_unknown", "non_ai", "passthrough"
]
Action = Literal["allow", "warn", "block_destination", "block_content"]

from .catalog import AI_DOMAINS  # noqa: E402  (catalogo semilla)
from .detect.model import (  # noqa: E402
    ETIQUETAS_POR_DEFECTO,
    ETIQUETAS_PRECISAS,
    UMBRAL_POR_DEFECTO,
)
from .suffixes import most_specific_match  # noqa: E402

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


# Dos formas de tratar una IA no aprobada, y la eleccion es de la empresa:
#
#   estricto     se corta el destino. Nadie usa lo que no esta aprobado.
#   equilibrado  se deja usar, pero se inspecciona cada envio y no sale ni un
#                dato sensible. El uso queda igual registrado en el panel, asi
#                que la visibilidad del shadow AI no se pierde.
#
# El segundo es mas facil de sostener en una empresa real: bloquear la
# herramienta que la gente ya usa termina en excepciones, VPNs y telefonos
# personales, que es exactamente donde nadie ve nada.
MODOS: dict[str, str] = {"estricto": "block_destination", "equilibrado": "inspect"}
MODO_POR_DEFECTO = "equilibrado"


def _accion_para_no_aprobadas() -> str:
    modo = os.environ.get("AEGIS_MODO", MODO_POR_DEFECTO).strip().lower()
    return MODOS.get(modo, MODOS[MODO_POR_DEFECTO])


@dataclass(frozen=True)
class CustomRule:
    """Una regla de deteccion escrita por la empresa, no por nosotros.

    El patron viaja como texto y se compila recien en detect/ruleset.py: si la
    regex es invalida, la regla se descarta ahi sin tumbar al agente. Es una
    dataclass congelada para que Policy siga siendo hashable.
    """

    id: str
    pattern: str
    category: str = "internal_data"
    severity: str = "high"


# Los valores que el motor entiende. Cualquier otra cosa que llegue de la web
# se corrige al default en vez de propagarse: una severidad desconocida hace
# KeyError en el orden de severidad del engine.
_CATEGORIAS_VALIDAS = frozenset({"secret", "pii", "internal_data"})
_SEVERIDADES_VALIDAS = frozenset({"critical", "high", "medium", "low"})


@dataclass(frozen=True)
class Policy:
    """Politica de la empresa. En produccion llega del backend y se cachea en disco."""

    tenant_id: str = "acme"
    approved_ai: frozenset[str] = field(default_factory=lambda: frozenset({"claude.ai", "api.anthropic.com"}))
    # Que hacer cuando sale un dato sensible hacia un dominio que todavia no
    # esta clasificado (ver decide._decide_destino_desconocido). "warn" es el
    # default: registra y deja pasar, porque el valor de esta rama es
    # descubrir el destino para que Haiku lo investigue, no frenar el primer
    # envio. "block_content" lo trata con la misma autoridad que una IA
    # conocida. "allow" es la salida de emergencia: ni siquiera se paga el
    # barrido barato.
    unknown_domain_action: Action = "warn"
    unapproved_ai_action: str = field(default_factory=_accion_para_no_aprobadas)
    # Que hacer con lo que encuentra el modelo. Por defecto manda la categoria:
    # una contrasena o un dato de empresa cortan igual que si los hubiera visto
    # T1, pero un dato personal suelto (nombre, direccion) solo advierte, porque
    # ahi el costo de un falso positivo es mas alto que el de dejarlo pasar.
    # "warn" es la salida de emergencia completa para la empresa que no confia
    # en el modelo: con eso, absolutamente ningun hallazgo del modelo bloquea,
    # sin importar la categoria.
    model_action: str = field(
        default_factory=lambda: os.environ.get("AEGIS_T2_ACCION", "block")
    )
    # Que etiquetas del modelo tienen autoridad para cortar un envio. Las demas
    # avisan: quedan en el panel y alimentan la leccion, pero no frenan a nadie.
    # Se decide por etiqueta y no por categoria porque dos etiquetas del mismo
    # tipo de dato pueden medir muy distinto: "nombre de cliente" se equivoca en
    # 1 de 36 frases normales y "empresa" en 6, y las dos son internal_data.
    model_block_labels: frozenset[str] = field(
        default_factory=lambda: frozenset(ETIQUETAS_PRECISAS)
    )
    block_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"secret", "internal_data"})
    )
    warn_categories: frozenset[str] = field(default_factory=lambda: frozenset({"pii"}))
    # Version del criterio de arriba, pero solo para lo que encuentra el modelo:
    # con esto una empresa puede confiar mas o menos en T2 que en T1 sin tocar
    # como se tratan las reglas deterministas.
    model_block_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"secret", "internal_data"})
    )
    # Que etiquetas le pide la empresa al modelo y con que umbral de confianza.
    # Hoy son las medidas en detect/model.py, pero una empresa con sus propios
    # datos internos puede agregar o sacar etiquetas sin tocar codigo.
    model_labels: tuple[str, ...] = ETIQUETAS_POR_DEFECTO
    model_threshold: float = UMBRAL_POR_DEFECTO
    # Que hacer cuando la capa D detecta un punto ciego (una app que no pasa
    # por el proxy). "warn" solo lo reporta; "block" corta la conexion. El
    # mecanismo que lee este campo lo construye otra tarea: aca solo se
    # declara y se serializa.
    blind_spot_action: str = "warn"
    # Reglas T1 que la empresa apago por id (por ejemplo "email_address" si
    # mandar correos a la IA es parte del trabajo). Tambien alcanza a los
    # hallazgos sinteticos (bulk_pii_export, archivo_critico); no toca lo que
    # encuentra el modelo, que tiene sus propias perillas arriba.
    disabled_rules: frozenset[str] = field(default_factory=frozenset)
    # Terminos literales que no pueden salir: el nombre del proyecto secreto,
    # el cliente que nadie puede nombrar. En la web esto es un textarea. La
    # accion no se configura por termino: todos comparten una categoria y la
    # categoria ya decide via block_categories/warn_categories.
    forbidden_terms: tuple[str, ...] = ()
    forbidden_terms_category: str = "internal_data"
    # Reglas regex escritas por la empresa. Mas poder que los terminos (y mas
    # riesgo): una regex invalida se descarta al compilar, no aca.
    custom_rules: tuple[CustomRule, ...] = ()

    def a_dict(self) -> dict[str, Any]:
        """Serializa la politica a tipos JSON, estable y diffeable.

        Los frozenset se ordenan al convertirlos a lista para que el archivo
        no cambie de una corrida a otra solo por el orden de iteracion.
        """

        return {
            "tenant_id": self.tenant_id,
            "approved_ai": sorted(self.approved_ai),
            "unknown_domain_action": self.unknown_domain_action,
            "unapproved_ai_action": self.unapproved_ai_action,
            "model_action": self.model_action,
            "model_block_categories": sorted(self.model_block_categories),
            "model_block_labels": sorted(self.model_block_labels),
            "block_categories": sorted(self.block_categories),
            "warn_categories": sorted(self.warn_categories),
            "model_labels": list(self.model_labels),
            "model_threshold": self.model_threshold,
            "blind_spot_action": self.blind_spot_action,
            "disabled_rules": sorted(self.disabled_rules),
            "forbidden_terms": list(self.forbidden_terms),
            "forbidden_terms_category": self.forbidden_terms_category,
            "custom_rules": [
                {
                    "id": regla.id,
                    "pattern": regla.pattern,
                    "category": regla.category,
                    "severity": regla.severity,
                }
                for regla in self.custom_rules
            ],
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, Any]) -> "Policy":
        """Reconstruye la politica desde un dict, tolerante en ambas puntas.

        Una clave ausente cae al default de la dataclass (no al default_factory
        de esta funcion, para no duplicar el criterio en dos lugares). Una
        clave desconocida se ignora: una politica escrita por un backend mas
        nuevo no puede romper un agente viejo.
        """

        base = cls()
        campos_frozenset = (
            "approved_ai",
            "model_block_categories",
            "model_block_labels",
            "block_categories",
            "warn_categories",
            "disabled_rules",
        )
        campos_tupla = ("model_labels", "forbidden_terms")
        campos_simples = (
            "tenant_id",
            "unknown_domain_action",
            "unapproved_ai_action",
            "model_action",
            "model_threshold",
            "blind_spot_action",
            "forbidden_terms_category",
        )

        valores: dict[str, Any] = {}
        for campo in campos_simples:
            valores[campo] = datos.get(campo, getattr(base, campo))
        for campo in campos_frozenset:
            valores[campo] = (
                frozenset(datos[campo]) if campo in datos else getattr(base, campo)
            )
        for campo in campos_tupla:
            valores[campo] = (
                tuple(datos[campo]) if campo in datos else getattr(base, campo)
            )
        valores["custom_rules"] = _custom_rules_tolerantes(
            datos.get("custom_rules", ())
        )

        return cls(**valores)


def _custom_rules_tolerantes(entradas: Any) -> tuple[CustomRule, ...]:
    """Convierte lo que haya mandado la web en reglas utilizables.

    Una entrada rota se salta y una categoria o severidad que el motor no
    conoce se corrige al default: la politica la edita gente, y un formulario
    a medio guardar no puede dejar a la empresa sin proteccion.
    """

    reglas: list[CustomRule] = []
    if not isinstance(entradas, (list, tuple)):
        return ()
    for entrada in entradas:
        if isinstance(entrada, CustomRule):
            entrada = {
                "id": entrada.id,
                "pattern": entrada.pattern,
                "category": entrada.category,
                "severity": entrada.severity,
            }
        if not isinstance(entrada, dict):
            continue
        rule_id = entrada.get("id")
        patron = entrada.get("pattern")
        if not rule_id or not patron:
            continue
        categoria = entrada.get("category", "internal_data")
        if categoria not in _CATEGORIAS_VALIDAS:
            categoria = "internal_data"
        severidad = entrada.get("severity", "high")
        if severidad not in _SEVERIDADES_VALIDAS:
            severidad = "high"
        reglas.append(
            CustomRule(
                id=str(rule_id),
                pattern=str(patron),
                category=categoria,
                severity=severidad,
            )
        )
    return tuple(reglas)


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

    La comparacion camina el host de mas especifico a menos (ver
    suffixes.py): unos pocos lookups de hash, no un barrido de todo el
    conjunto. Es lo que permite que la lista negra crezca a miles de
    dominios sin que el costo por peticion se mueva.
    """

    match = most_specific_match(host, domains)
    return len(match) if match else 0


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


def _decide_destino_desconocido(categories: set[str], policy: Policy) -> Action:
    """Que hacer con lo que sale hacia un dominio que todavia no se sabe si es IA.

    Sin hallazgos no hay nada que decidir: pasa igual que hoy, sin importar el
    modo. Con hallazgos, la autoridad la da unknown_domain_action: "warn"
    (el default) registra y deja pasar porque el valor de esta rama es
    descubrir el destino, no cortar el primer envio; "block_content" lo trata
    igual que a una IA conocida, con las mismas categorias; "allow" es la
    salida de emergencia que reproduce el embudo de siempre.
    """

    modo = policy.unknown_domain_action
    if not categories or modo == "allow":
        action: Action = "allow"
    else:
        if modo == "block_content":
            if categories & policy.block_categories:
                action = "block_content"
            else:
                if categories & policy.warn_categories:
                    action = "warn"
                else:
                    action = "allow"
        else:
            action = "warn"
    return action


def decide(classification: Classification, categories: set[str], policy: Policy) -> Action:
    """Cruza el destino con lo que se encontro en el contenido.

    El orden importa: el destino manda. Un dominio de IA no aprobada se corta
    aunque el contenido venga limpio, porque el problema ahi es el shadow AI, no
    el dato. Y en una IA aprobada no se corta el destino nunca: se corta el dato,
    que es lo que permite que la gente siga trabajando con la herramienta.
    """

    if classification == "passthrough":
        action: Action = "allow"
    else:
        if classification == "non_ai":
            action = _decide_destino_desconocido(categories, policy)
        else:
            if classification == "ai_unapproved" and policy.unapproved_ai_action == "block_destination":
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
