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


# Las cinco formas de escribir un parametro segun el driver que uses.
_PLACEHOLDERS = re.compile(r"\?|:\w+|%\(\w+\)s|%s|\$\d+|@\w+")


def has_literal_values(values: str) -> bool:
    """Distingue un INSERT con datos de una consulta preparada.

    Un desarrollador pega plantillas con VALUES (?, ?) todo el dia; bloquearlas
    convierte a Aegis en un obstaculo y nadie lo deja instalado una semana.
    """

    remainder = _PLACEHOLDERS.sub("", values).strip(" ,\t\n\r")
    return bool(remainder)


# Familia 1: credenciales. Formato conocido, confianza alta, bloqueo directo.
_SECRETS: tuple[Rule, ...] = (
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
        id="sendgrid_api_key",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}"),
        description="API key de SendGrid",
    ),
    Rule(
        id="mailgun_api_key",
        category="secret",
        severity="critical",
        confidence=0.97,
        pattern=_compile(r"\bkey-[0-9a-f]{32}\b"),
        description="API key de Mailgun",
    ),
    Rule(
        id="digitalocean_token",
        category="secret",
        severity="critical",
        confidence=0.99,
        pattern=_compile(r"\bdop_v1_[0-9a-f]{32,}"),
        description="Token de DigitalOcean",
    ),
    Rule(
        id="huggingface_token",
        category="secret",
        severity="critical",
        confidence=0.97,
        pattern=_compile(r"\bhf_[A-Za-z0-9]{30,}"),
        description="Token de Hugging Face",
    ),
    Rule(
        id="twilio_credential",
        category="secret",
        severity="high",
        confidence=0.95,
        pattern=_compile(r"\b(?:AC|SK)[0-9a-f]{32}\b"),
        description="Identificador o llave de Twilio",
    ),
    Rule(
        id="azure_storage_key",
        category="secret",
        severity="critical",
        confidence=0.98,
        pattern=_compile(r"AccountKey=[A-Za-z0-9+/=]{40,}"),
        description="Llave de cuenta de almacenamiento de Azure",
    ),
    Rule(
        id="generic_secret_assignment",
        category="secret",
        severity="high",
        confidence=0.75,
        pattern=_compile(
            # Sin limite de palabra al inicio: en AWS_SECRET_ACCESS_KEY o en
            # TWILIO_AUTH_TOKEN los guiones bajos son caracteres de palabra y el
            # limite nunca casa. El ancla [:=] es la que evita falsos positivos.
            # La barra opcional cubre el JSON, que llega con las comillas
            # escapadas porque el prompt viaja dentro de otro JSON.
            r"(?i)(?:api[_-]?key|secret|token|password|passwd|pwd|credential"
            r"|accountkey|access[_-]?key)s?\s*[:=]\s*\\?[\"']?([^\s\"'\\]{12,})"
        ),
        description="Asignacion de credencial con valor de alta entropia",
        group=1,
        validator=looks_random,
    ),
)

# Familia 2: datos de la empresa. Un .env es lo mas facil de detectar y lo menos
# frecuente; lo que la gente pega de verdad son consultas, tablas y exports.
_INTERNAL_DATA: tuple[Rule, ...] = (
    Rule(
        id="sql_dump_header",
        category="internal_data",
        severity="critical",
        confidence=0.98,
        pattern=_compile(
            r"(?i)(?:--\s*(?:MySQL|PostgreSQL|MariaDB)\s+(?:\w+\s+)?dump|pg_dump"
            r"|mysqldump|--\s*Dumping data for table)"
        ),
        description="Volcado de base de datos",
        redact_as="type",
        kind="db_dump",
    ),
    Rule(
        id="sql_insert_rows",
        category="internal_data",
        severity="high",
        confidence=0.9,
        pattern=_compile(
            r"(?i)\bINSERT\s+INTO\s+[`\"\[]?\w+[`\"\]]?\s*\([^)]*\)\s*VALUES\s*"
            r"\(([^)]{0,300})\)"
        ),
        description="Filas de una tabla con datos reales",
        group=1,
        validator=lambda values: has_literal_values(values),
        redact_as="type",
        kind="db_rows",
    ),
    Rule(
        id="sql_schema_sensitive",
        category="internal_data",
        severity="high",
        confidence=0.88,
        pattern=_compile(
            r"(?i)CREATE\s+TABLE[\s\S]{0,400}?\b"
            r"(?:password|passwd|contrasena|salario|salary|cedula|documento|tarjeta"
            r"|card_number|ssn|nit)\b"
        ),
        description="Esquema de tabla con columnas sensibles",
        redact_as="type",
        kind="db_schema",
    ),
    Rule(
        id="csv_pii_export",
        category="internal_data",
        severity="critical",
        confidence=0.9,
        # Una cabecera con correo y otro dato personal en la misma linea es un
        # export de base de datos, no una mencion suelta.
        pattern=_compile(
            r"(?im)^[^\n]{0,200}?\b(?:email|correo|e-mail)\b[^\n]{0,200}?[;,\t]"
            r"[^\n]{0,200}?\b(?:telefono|tel[eé]fono|phone|celular|documento"
            r"|c[eé]dula|nit|direcci[oó]n|salario|nombre)\b"
        ),
        description="Cabecera de export con datos personales",
        redact_as="type",
        kind="csv_export",
    ),
    Rule(
        id="confidentiality_marker",
        category="internal_data",
        severity="medium",
        confidence=0.7,
        pattern=_compile(
            r"(?i)\b(?:confidencial|uso interno|no distribuir|bajo nda"
            r"|internal use only|company confidential)\b"
        ),
        description="Documento marcado como interno o confidencial",
        redact_as="type",
        kind="internal_doc",
    ),
)

# Familia 3: datos personales. Se advierte por defecto y se bloquea en volumen,
# porque un correo suelto es una mencion y trescientos son una base de clientes.
_PII: tuple[Rule, ...] = (
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
        id="latam_national_id",
        category="pii",
        severity="high",
        confidence=0.9,
        # Sin la palabra que lo antecede, una cedula es indistinguible de
        # cualquier numero de seis a doce digitos.
        pattern=_compile(
            r"(?i)\b(?:c\.?c\.?|cedula|c[eé]dula|documento|nit|rut|cpf|dni)\b"
            r"\s*[:#\-]?\s*\d[\d.\- ]{5,14}\d"
            # La CURP mexicana mezcla letras y digitos, no sirve el patron de arriba.
            r"|\bcurp\b\s*[:#\-]?\s*[A-Z0-9]{16,18}"
        ),
        description="Documento de identidad latinoamericano",
        redact_as="type",
        kind="national_id",
    ),
    Rule(
        id="iban",
        category="pii",
        severity="high",
        confidence=0.9,
        pattern=_compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}\b"),
        description="Cuenta bancaria en formato IBAN",
        redact_as="type",
        kind="iban",
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

RULES: tuple[Rule, ...] = _SECRETS + _INTERNAL_DATA + _PII

RULES_BY_ID = {rule.id: rule for rule in RULES}
