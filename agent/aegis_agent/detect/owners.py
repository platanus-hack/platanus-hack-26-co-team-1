from __future__ import annotations

# Una credencial que viaja hacia su propio dueño no es una fuga: es su uso normal.
#
# Suena obvio dicho asi, y sin embargo es lo que rompe a un DLP ingenuo apenas se
# instala. Claude Code manda su token a api.anthropic.com en cada peticion; el
# CLI de GitHub manda el suyo a github.com. Si eso se bloquea, la herramienta deja
# de autenticarse y el empleado desinstala Aegis el mismo dia.
#
# La distincion que importa es la direccion: sk-ant-... hacia api.anthropic.com es
# trabajo; el mismo sk-ant-... hacia chatgpt.com es una fuga.

# Los duenos son los ENDPOINTS de la API, no las aplicaciones web del mismo
# proveedor: pegar tu llave de OpenAI en el chat de chatgpt.com no es usarla, es
# justamente la fuga que hay que atrapar. Claude Code se autentica contra
# claude.com con un token OAuth, que no es una llave de API y cae en SIN_DUENO.
DUENOS: dict[str, tuple[str, ...]] = {
    "anthropic_api_key": ("anthropic.com", "claude.com"),
    "openai_api_key": ("openai.com",),
    "github_token": ("github.com", "githubusercontent.com"),
    "google_api_key": ("google.com", "googleapis.com", "gstatic.com"),
    "slack_token": ("slack.com",),
    "stripe_secret_key": ("stripe.com",),
    "sendgrid_api_key": ("sendgrid.com", "twilio.com"),
    "mailgun_api_key": ("mailgun.net", "mailgun.com"),
    "twilio_credential": ("twilio.com",),
    "digitalocean_token": ("digitalocean.com",),
    "huggingface_token": ("huggingface.co",),
    "azure_storage_key": ("azure.com", "windows.net"),
    "aws_access_key_id": ("amazonaws.com",),
}

# Estas no tienen dueño reconocible: un JWT o una asignacion generica pueden ser
# de cualquiera. Se dejan pasar cuando el destino es el servicio con el que la
# herramienta se esta autenticando, y eso lo decide la ruta, no la regla.
SIN_DUENO = ("jwt", "generic_secret_assignment")

# Rutas donde una credencial es, por definicion, la que se esta presentando para
# entrar. Bloquear aca es impedir que la herramienta inicie sesion.
RUTAS_DE_AUTENTICACION = (
    "/oauth",
    "/token",
    "/auth",
    "/login",
    "/signin",
    "/session",
    "/.well-known/",
    "/v1/organizations",
)


def _mismo_dominio(host: str, dueno: str) -> bool:
    host = host.lower().strip(".")
    return host == dueno or host.endswith("." + dueno)


def es_su_dueno(rule_id: str, host: str) -> bool:
    """¿La credencial va hacia el servicio que la emitio?"""

    duenos = DUENOS.get(rule_id, ())
    return any(_mismo_dominio(host, dueno) for dueno in duenos)


def es_ruta_de_autenticacion(path: str) -> bool:
    lowered = path.lower()
    return any(ruta in lowered for ruta in RUTAS_DE_AUTENTICACION)


def exento(rule_id: str, host: str, path: str) -> bool:
    """Hallazgos que no cuentan como fuga por el destino al que van."""

    if es_su_dueno(rule_id, host):
        resultado = True
    else:
        # Sin dueño reconocible solo se perdona en el saludo de autenticacion,
        # que es donde la credencial es el pasaje y no la carga.
        resultado = rule_id in SIN_DUENO and es_ruta_de_autenticacion(path)
    return resultado
