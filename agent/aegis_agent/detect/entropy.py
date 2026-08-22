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
