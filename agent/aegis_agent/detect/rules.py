from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .entropy import (
    looks_random,
    luhn_valid,
    parece_contrasena,
    parece_documento_de_identidad,
    parece_secreto_asignado,
)
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


# "Clave" en espanol son dos cosas distintas. Una clave primaria, foranea o
# publica no se oculta: es vocabulario de base de datos y de criptografia, y
# aparecia constantemente en texto de trabajo legitimo. Lo comparten las dos
# reglas en espanol para que no se separen con el tiempo.
_CLAVE_NO_SECRETA = (
    r"(?!s?\s+(?:primaria|primarias|foranea|foraneas|unica|unicas|compuesta"
    r"|candidata|natural|subrogada|publica|publicas|simetrica|asimetrica))"
)

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
        validator=parece_secreto_asignado,
    ),
    Rule(
        id="credencial_en_espanol",
        category="secret",
        severity="critical",
        confidence=0.85,
        pattern=_compile(
            # Nadie escribe password=... cuando le esta contando algo a un chat.
            # Escribe "la contrasena del servidor de produccion es X", con media
            # frase entre la palabra y el valor. Medido sobre el corpus: el
            # modelo local no encuentra ninguna de estas y una regla las ve.
            #
            # Lo que sostiene la precision es looks_random sobre el valor: sin
            # eso, "la clave es la de siempre" entraria como incidente critico.
            r"(?i)(?:contrasena|contrasenas|credencial|credenciales"
            r"|usuario y clave|acceso|clave" + _CLAVE_NO_SECRETA + r"s?)"
            r"\b[^.\n]{0,40}?\s(?:es|son|:)\s+"
            r"\\?[\"']?([^\s\"'\\]{12,})"
        ),
        description="Credencial dicha en lenguaje natural, no como asignacion",
        group=1,
        validator=looks_random,
    ),
    Rule(
        id="credencial_en_espanol_sin_verbo",
        category="secret",
        severity="critical",
        confidence=0.8,
        pattern=_compile(
            # La regla de arriba necesita un verbo entre la palabra y el valor
            # ("la contrasena ES X"). Media conversacion real no lo tiene: "entra
            # con la clave Temporal#2026", "el acceso es aegis / Sup3rS3cret".
            # Medido sobre el corpus: de las tres credenciales dichas en lenguaje
            # natural, aquella veia una y estas dos se escapaban enteras, sin que
            # el modelo local viera ninguna (0/3). Una contrasena es lo mas grave
            # que puede salir y no puede depender de como este redactada.
            #
            # Tres cosas sostienen la precision, y las tres se midieron:
            #
            #   - La ventana es corta (24 caracteres). Con 30, "la credencial se
            #     rota segun la ISO27001_v3" entraba como incidente critico.
            #   - El valor tiene que MEZCLAR clases de caracteres: minuscula, mas
            #     digito, mas mayuscula o simbolo. Es lo que exige cualquier
            #     politica de contrasenas y lo que ninguna palabra comun tiene.
            #     Por eso el (?i:) va solo sobre las palabras ancla: aplicado a
            #     todo el patron, [A-Z] casaria minusculas y la mezcla dejaria de
            #     existir.
            #   - "clave" se excluye cuando la sigue jerga de base de datos o de
            #     criptografia: una clave primaria o una clave publica no son un
            #     secreto, y aparecian constantemente.
            r"(?i:\b(?:contrasena|contrasenas|password|passwd|credencial"
            r"|credenciales|acceso|login|usuario"
            r"|clave" + _CLAVE_NO_SECRETA + r"s?)\b)"
            r"[^.\n]{0,24}?\s"
            # La barra invertida corta el valor a proposito. El prompt viaja
            # dentro de un JSON, donde "explicitamente" se escribe
            # "expl\u00edcitamente": el escape le mete digitos a una palabra
            # espanola corriente y la vuelve indistinguible de una contrasena.
            # Cerca de la palabra "usuario" eso bloqueaba una sesion entera de
            # Claude Code por su propio archivo de memoria. La version
            # desescapada del cuerpo es otra vista y ahi la credencial de verdad
            # se sigue viendo, asi que no se pierde nada.
            r"(?=[^\s\\]{10,64}(?:[\s.,;:)\"'\\]|$))"
            r"(?=[^\s\\]*[a-z])"
            r"(?=[^\s\\]*[A-Z0-9])"
            r"(?=[^\s\\]*\d)"
            r"([^\s\"',;\\]{10,64})"
        ),
        description="Credencial nombrada sin verbo, por la forma del valor",
        group=1,
        validator=parece_contrasena,
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
        #
        # Pero la palabra casi nunca esta pegada al numero. En espanol se dice
        # "mi numero de cedula ES 1.020.345.678" y "la cedula DEL CLIENTE es
        # 79.482.113": con la version que exigia adyacencia, ninguna de las dos
        # se veia. La cedula es el dato personal mas comun que existe en
        # Colombia, asi que eso no era un caso borde.
        #
        # Las anclas van separadas en dos grupos porque no valen lo mismo.
        # "cedula", "NIT" o "DNI" nombran un documento y nada mas, asi que
        # aguantan una ventana de 24 caracteres. "documento" es una palabra
        # comun ("el documento 2024-15 del contrato", "el documento ISO
        # 9001-2015") y se queda pegada al numero, como estaba.
        pattern=_compile(
            r"(?i)(?:"
            r"\b(?:c\.?c\.?|c[eé]dulas?|nit|rut|cpf|dni|documento\s+de\s+identidad)\b"
            r"[^.\n\d]{0,24}?[:#\-]?\s*\d[\d.\- ]{5,14}\d"
            r"|\bdocumento\b\s*[:#\-]?\s*\d[\d.\- ]{5,14}\d"
            # La CURP mexicana mezcla letras y digitos, no sirve el patron de arriba.
            r"|\bcurp\b\s*[:#\-]?\s*[A-Z0-9]{16,18}"
            r")"
        ),
        description="Documento de identidad latinoamericano",
        redact_as="type",
        kind="national_id",
        validator=parece_documento_de_identidad,
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
