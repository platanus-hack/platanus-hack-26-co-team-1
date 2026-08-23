from __future__ import annotations

import math
from collections import Counter

# Una clave en base64 ronda 4.5-5.5 bits por caracter; una frase en espanol rara
# vez pasa de 3.5. El umbral va justo debajo para no perder claves cortas.
DEFAULT_ENTROPY_THRESHOLD = 3.2

MIN_SECRET_LEN = 12


def shannon_entropy(value: str) -> float:
    if not value:
        entropy = 0.0
    else:
        counts = Counter(value)
        length = len(value)
        entropy = -sum(
            (count / length) * math.log2(count / length) for count in counts.values()
        )
    return entropy


# Un valor que arranca con uno de estos no es una credencial: es marcado, una
# plantilla o un fragmento de codigo dentro de un texto. Aparecio en vivo, con
# Claude Code mandando su contexto: un `git ...` en markdown, precedido por la
# palabra "credencial", bloqueaba una sesion entera.
_INICIOS_DE_MARCADO = ("`", "<", "{", "$", "(", "[", "%", "*", "#", "|")


def looks_random(value: str, threshold: float = DEFAULT_ENTROPY_THRESHOLD) -> bool:
    """Filtro para las reglas genericas del tipo ``password = ...``.

    Sin esto, ``password = la del correo de siempre`` entra como incidente
    critico y el producto se vuelve ruido.
    """

    if len(value) < MIN_SECRET_LEN or value.startswith(_INICIOS_DE_MARCADO):
        result = False
    else:
        if " " in value.strip():
            result = False
        else:
            result = shannon_entropy(value) >= threshold
    return result


# Ningun secreto real lleva parentesis, llaves o corchetes. Una llamada a una
# funcion, si. base64 usa +, / y =, que quedan permitidos a proposito.
_CARACTERES_DE_CODIGO = ("(", ")", "{", "}", "[", "]", "<", ">", ";")


def parece_expresion_de_codigo(value: str) -> bool:
    """El valor no es un secreto sino un pedazo de programa.

    `const password = hashPassword(input.value)` es lo que un desarrollador pega
    diez veces por dia, y hasta que esto existio lo bloqueaba como incidente
    critico. Un falso bloqueo sobre codigo es de los que hacen que el equipo de
    desarrollo pida que le saquen Aegis.
    """

    return any(caracter in value for caracter in _CARACTERES_DE_CODIGO)


def parece_secreto_asignado(value: str) -> bool:
    """El validador de las reglas genericas `password = ...`."""

    return looks_random(value) and not parece_expresion_de_codigo(value)


LARGO_MINIMO_CONTRASENA = 10


def parece_contrasena(value: str) -> bool:
    """Un valor con forma de contrasena elegida por una persona.

    La entropia sola no alcanza y por eso este validador existe aparte de
    looks_random: `Sup3rS3cret` da 2.91 bits, por debajo del umbral, y es
    exactamente la clave que una politica de empresa obliga a poner. Lo que
    separa una contrasena de una palabra comun no es el desorden sino la mezcla
    de clases de caracteres, que es justo lo que esa politica exige.

    La mezcla la impone la expresion regular, que asi puede seguir buscando
    dentro de la frase hasta dar con un valor que la cumpla. Aca queda lo que la
    regex no sabe: el largo y que no sea marcado. El marcado ya nos mordio una
    vez, con un fragmento de codigo entre comillas invertidas bloqueando una
    sesion entera de Claude Code.
    """

    return (
        not value.startswith(_INICIOS_DE_MARCADO)
        and LARGO_MINIMO_CONTRASENA <= len(value) <= 64
    )


def parece_documento_de_identidad(value: str) -> bool:
    """Descarta lo que quedo dentro de la ventana y no es un documento.

    La ventana entre la palabra y el numero deja entrar cosas como
    "el documento 2024-15" o "la norma 9001-2015". Un documento de identidad
    latinoamericano tiene entre siete y catorce digitos; un ano, un rango o una
    version tienen menos, o mas de uno.
    """

    digitos = sum(caracter.isdigit() for caracter in value)
    return "curp" in value.lower() or 7 <= digitos <= 14


def luhn_valid(digits: str) -> bool:
    only_digits = [int(char) for char in digits if char.isdigit()]
    if not 13 <= len(only_digits) <= 19:
        valid = False
    else:
        total = 0
        parity = len(only_digits) % 2
        for index, digit in enumerate(only_digits):
            if index % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        valid = total % 10 == 0
    return valid


def tiene_mezcla_de_clases(value: str) -> bool:
    """Minuscula + digito + (mayuscula o simbolo).

    Es lo que exige cualquier politica de contrasenas de empresa y lo que ninguna
    palabra comun tiene. Hasta ahora esta condicion vivia SOLO dentro de la
    expresion regular de una de las dos reglas de credencial en espanol, y esa
    asimetria es la que dejaba escapar credenciales: la otra regla, la que tiene
    la ventana larga, no podia usar el mismo criterio porque no estaba escrito en
    ningun lado reutilizable.
    """

    return (
        any(c.islower() for c in value)
        and any(c.isdigit() for c in value)
        and any(c.isupper() or not c.isalnum() for c in value)
    )


def parece_credencial_dicha(value: str) -> bool:
    """El validador de la regla de credencial con verbo ("la clave ES X").

    Acepta dos cosas distintas, y hacen falta las dos:

      - un valor de alta entropia, que es una llave generada por una maquina;
      - un valor con mezcla de clases, que es una contrasena elegida por una
        persona.

    La segunda mitad no estaba, y ahi se iba la fuga. Medido sobre el corpus
    generado: "la clave del servidor de produccion es Sup3rS3cret1" escapaba
    entera. `Sup3rS3cret1` da 3.08 bits --por debajo del umbral de 3.2-- y es
    exactamente la clave que una politica de empresa obliga a poner. La otra
    regla, la que si sabe de mezcla, tiene una ventana de 24 caracteres y "del
    servidor de produccion es" son 29: no llegaba.

    Y la mezcla es obligatoria en esa segunda mitad, no opcional. Sin ella, "la
    clave es infraestructura" entra como incidente critico: son 15 caracteres sin
    espacios y pasan cualquier filtro de largo.
    """

    return not parece_expresion_de_codigo(value) and (
        looks_random(value) or (parece_contrasena(value) and tiene_mezcla_de_clases(value))
    )
