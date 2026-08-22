"""Valores que tienen forma de credencial y no son ninguna.

La medicion que motivo este modulo: de doce frases de trabajo legitimo, cinco
disparaban un hallazgo, y dos de esas cinco eran de categoria ``secret``, que
CORTA el envio:

    «en la documentacion usan sk-proj-XXXXXXXXXXXXXXXXXXXX como placeholder»
    «el .env.example tiene DATABASE_URL=postgres://user:password@localhost:5432/db»

El segundo es el que mas duele: ``.env.example`` es el archivo que existe
precisamente para NO tener secretos, y un desarrollador que le pregunta a Claude
Code por el suyo se come un 403. Ese patron ya mordio antes en este proyecto
--el token de Claude Code hacia su propio dueno-- y volvio a entrar por otra
puerta. Un falso bloqueo sobre la persona que mas rapido desinstala no es un
detalle de precision: es el producto.

## Lo que este modulo NO hace, y por que

No filtra por la palabra "example". La llave canonica de la documentacion de AWS
es ``AKIAIOSFODNN7EXAMPLE``: si "example" alcanzara para descartar un valor,
cualquiera saca una credencial de verdad agregandole ese sufijo, y el filtro que
existe para bajar el ruido se convierte en el bypass mas facil del producto. Un
marcador de plantilla tiene que ser algo que un secreto real no pueda tener.

Por eso las tres senales de abajo son estructurales y no lexicas: una corrida de
caracteres identicos, un valor que ES la palabra plantilla, o una cadena de
conexion cuyo host Y cuyas credenciales son los dos genericos.
"""

from __future__ import annotations

import re

# 1. Corrida de caracteres identicos: XXXXXXXX, 00000000, ********, aaaaaaaa.
#
#    La calibracion de este numero importa mas de lo que parece, y hay que
#    razonarla desde el lado que duele. Un falso positivo aca deja pasar un
#    secreto de VERDAD --el filtro apaga la regla-- y eso es peor que el ruido
#    que vino a resolver. Asi que no alcanza con que exista una corrida: tiene
#    que DOMINAR el valor, que es lo que separa una plantilla de un token real
#    con dos caracteres repetidos por casualidad.
#
#    En un token hexadecimal de 40 caracteres, la probabilidad de una corrida de
#    seis identicos ronda 1 en 30.000: baja, pero no cero, y con suficientes
#    empleados eso pasa. Una corrida de doce es imposible en la practica.
LARGO_MINIMO_DE_CORRIDA = 6
LARGO_DE_CORRIDA_CONCLUYENTE = 12
FRACCION_DE_CORRIDA = 0.4

_CORRIDA = re.compile(r"(.)\1{" + str(LARGO_MINIMO_DE_CORRIDA - 1) + r",}")


def _corrida_dominante(valor: str) -> bool:
    """Hay una corrida de caracteres identicos que manda en el valor."""

    corridas = [len(m.group(0)) for m in _CORRIDA.finditer(valor)]
    if not corridas:
        resultado = False
    else:
        mas_larga = max(corridas)
        resultado = mas_larga >= LARGO_DE_CORRIDA_CONCLUYENTE or (
            mas_larga / len(valor) >= FRACCION_DE_CORRIDA
        )
    return resultado

# 2. Palabras que solo aparecen en una plantilla, buscadas como TOKEN completo
#    dentro del valor (separado por _ - . : / o cambio de caja), nunca como
#    subcadena. "tu" suelta es media palabra en espanol; "TU_CLAVE" no.
_PALABRAS_DE_PLANTILLA = frozenset(
    {
        # espanol
        "reemplazar",
        "reemplaza",
        "cambiar",
        "cambia",
        "poner",
        "pone",
        "aca",
        "aqui",
        "tu",
        "tus",
        "mi",
        "clave",
        "contrasena",
        "pendiente",
        "falta",
        # ingles
        "your",
        "yours",
        "here",
        "changeme",
        "change",
        "replace",
        "insert",
        # "me" y "please" salen de CHANGE_ME_PLEASE. Sueltas serian palabras
        # demasiado comunes, pero la fraccion las sostiene: hacen falta varias
        # para que un valor cuente como plantilla.
        "me",
        "please",
        "favor",
        "todo",
        "fixme",
        "tbd",
        "dummy",
        "fake",
        "placeholder",
        "redacted",
        "removed",
        "hidden",
        "masked",
        "missing",
        "notset",
        "none",
        "null",
        "undefined",
        "xxx",
        "yyy",
        "zzz",
        "foo",
        "bar",
        "baz",
        "abc",
    }
)

# Un valor de plantilla casi siempre es SOLO palabras de plantilla pegadas:
# YOUR_API_KEY, REEMPLAZAR_CON_TU_TOKEN, tu-clave-aca. Se pide que una fraccion
# alta de sus tokens lo sean, y no uno solo, para que un secreto de verdad que
# por casualidad contenga "abc" no se caiga.
FRACCION_DE_PLANTILLA = 0.5

_SEPARADORES = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

# Palabras que NO cuentan como plantilla aunque acompanen: son el nombre del
# dato, no el marcador. Sin esto, "API_KEY" sola ya daria 1/2 de fraccion.
_NOMBRES_DE_CAMPO = frozenset(
    {"api", "key", "keys", "token", "tokens", "secret", "secrets", "password",
     "passwd", "pwd", "credential", "credentials", "auth", "access", "id",
     "value", "valor", "sk", "pk", "env", "var"}
)


def _tokens(valor: str) -> list[str]:
    partes: list[str] = []
    for bruto in _SEPARADORES.split(valor):
        if bruto:
            partes.extend(t.lower() for t in _CAMEL.split(bruto) if t)
    return partes


def _es_plantilla_por_palabras(valor: str) -> bool:
    tokens = [t for t in _tokens(valor) if t not in _NOMBRES_DE_CAMPO]
    if not tokens:
        # Solo nombres de campo: API_KEY, TOKEN. No es un secreto.
        resultado = bool(_tokens(valor))
    else:
        plantilla = sum(1 for t in tokens if t in _PALABRAS_DE_PLANTILLA)
        resultado = plantilla / len(tokens) >= FRACCION_DE_PLANTILLA
    return resultado


# 3. Cadena de conexion de ejemplo. Se piden LAS DOS condiciones --host generico
#    Y credenciales genericas-- porque cada una sola tiene contraejemplos
#    legitimos: una base de produccion puede estar detras de un tunel en
#    localhost, y un usuario puede llamarse "admin" con una clave de verdad.
_HOSTS_GENERICOS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "host",
    "hostname",
    "example.com",
    "example.org",
    "ejemplo.com",
    "db",
    "database",
    "mydb",
    "midb",
)
_CREDENCIALES_GENERICAS = frozenset(
    {"user", "usuario", "username", "admin", "root", "test", "demo", "guest",
     "postgres", "mysql", "mongo", "redis", "password", "passwd", "pass",
     "secret", "clave", "contrasena", "1234", "12345", "123456", "changeme",
     "pwd", "dbuser", "dbpass"}
)
_CONEXION = re.compile(
    r"(?i)^[a-z0-9+]+://(?P<usuario>[^\s:@/]+):(?P<clave>[^\s:@/]+)@(?P<host>[^\s/:]+)"
)


def _es_conexion_de_ejemplo(valor: str) -> bool:
    match = _CONEXION.match(valor.strip())
    if match is None:
        resultado = False
    else:
        host = match.group("host").lower()
        host_generico = any(
            host == generico or host.endswith("." + generico)
            for generico in _HOSTS_GENERICOS
        )
        credenciales_genericas = (
            match.group("usuario").lower() in _CREDENCIALES_GENERICAS
            and match.group("clave").lower() in _CREDENCIALES_GENERICAS
        )
        resultado = host_generico and credenciales_genericas
    return resultado


def es_placeholder(valor: str) -> bool:
    """El valor tiene forma de credencial pero es una plantilla o un ejemplo.

    Se aplica sobre TODAS las reglas de categoria ``secret`` desde el motor, y no
    como validador de cada regla, porque las reglas de formato (una llave de
    OpenAI, un token de GitHub) no tienen validador: el formato les alcanzaba. Y
    es justamente ahi donde entro el falso positivo medido.
    """

    if not valor:
        resultado = False
    else:
        resultado = (
            _corrida_dominante(valor)
            or _es_plantilla_por_palabras(valor)
            or _es_conexion_de_ejemplo(valor)
        )
    return resultado
