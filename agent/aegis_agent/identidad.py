"""Que CUENTA esta usando la herramienta aprobada.

Todo el mercado permite o prohibe por DOMINIO, y ahi hay un hueco que se ve
apenas se nombra: si la empresa aprueba ChatGPT, `chatgpt.com` queda en verde
para todos. La cuenta corporativa y la cuenta personal gratuita del empleado
viajan por el mismo dominio, con el mismo TLS y el mismo aspecto. La segunda es
justamente la peor de las dos: es la que entrena con lo que le peguen.

"Aprobamos la herramienta" y "aprobamos la cuenta" no son la misma frase, y
hasta aca Aegis solo sabia decir la primera.

Tres decisiones que sostienen este archivo:

1. **Nunca se guarda la credencial, solo su huella.** Un `Authorization` es lo
   mas sensible que lleva un request. Se hashea con SHA-256 y se conservan doce
   caracteres: alcanza para comparar dos cuentas y no alcanza para reconstruir
   nada. La politica declara huellas, no llaves, asi que ni el panel ni el
   backend ven jamas un secreto de la empresa.

2. **La ausencia de identidad no acusa a nadie.** Es el error que haria esto
   inservible: un chat en el navegador se autentica con cookie y NO manda
   `Authorization`, y ChatGPT Enterprise tampoco. Tratar "sin identidad" como
   "cuenta personal" marcaria como fuga todo el uso sancionado, que es la forma
   mas rapida de que desinstalen Aegis. Por eso hay tres veredictos y no dos.

3. **Si la empresa no declaro ninguna cuenta, esto no opina.** Con la lista
   vacia toda cuenta seria ajena y el primer dia de instalacion se bloquearia
   la empresa entera. La comprobacion se enciende nombrando al menos una cuenta
   propia, nunca al reves; es el mismo criterio del ADR 0004 que ya gobierna
   `app_actions` y `user_actions`.

Sobre las cabeceras: las que estan abajo son las que usan hoy los proveedores
grandes, y la lista es una constante del modulo justamente porque cada uno hace
lo suyo y esto va a envejecer. Agregar un proveedor es agregar un nombre aca, no
tocar el motor. Lo que no cambia es la forma: un identificador de cuenta
explicito vale mas que una credencial, porque nombra a la organizacion en vez de
obligarnos a deducirla.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# Cuanto de la huella se conserva. Doce caracteres hex son 48 bits: de sobra
# para que dos cuentas distintas no colisionen en una empresa, y muy por debajo
# de lo que se necesitaria para atacar el hash. Ademas entra holgado en el
# limite de 32 caracteres que el contrato le pone a la evidencia.
LARGO_DE_HUELLA = 12

# Cabeceras que dicen QUIEN es la organizacion, sin rodeos. Se prefieren a
# cualquier credencial porque son estables: una empresa puede rotar su llave el
# martes y sigue siendo la misma cuenta.
CABECERAS_DE_CUENTA = (
    "chatgpt-account-id",
    "openai-organization",
    "anthropic-organization-id",
    "x-goog-authuser",
)

# Material de autenticacion. De aca NO sale el valor: sale su huella.
CABECERAS_DE_CREDENCIAL = (
    "authorization",
    "x-api-key",
    "x-goog-api-key",
)

# claude.ai no manda una cabecera de organizacion: la lleva en la ruta, como
# /api/organizations/<uuid>/chat_conversations. Es el mismo dato con otra forma.
_ORGANIZACION_EN_RUTA = re.compile(r"/organizations/([0-9a-fA-F][0-9a-fA-F-]{7,})")

CORPORATIVA = "corporativa"
AJENA = "ajena"
SIN_IDENTIDAD = "sin_identidad"


def huella(valor: str) -> str:
    """La huella de una credencial. Nunca su contenido."""

    return hashlib.sha256(valor.strip().encode("utf-8")).hexdigest()[:LARGO_DE_HUELLA]


def _normalizadas(cabeceras: Any) -> dict[str, str]:
    """Las cabeceras en minusculas, una sola vez por request.

    mitmproxy ya las trata sin distinguir mayusculas, pero un dict de Python no.
    Este modulo tiene que dar el mismo resultado con los dos: si dependiera de
    como se escribio `Authorization`, funcionaria en produccion y en los tests
    no, o -mucho peor- al reves.
    """

    try:
        pares = list(cabeceras.items())
    except (AttributeError, TypeError):
        pares = []
    return {
        str(nombre).lower(): str(valor).strip()
        for nombre, valor in pares
        if nombre and valor
    }


def _de_una_cuenta(cabeceras: dict[str, str]) -> str | None:
    """El identificador de organizacion, si el proveedor lo manda explicito."""

    encontrado = None
    for nombre in CABECERAS_DE_CUENTA:
        valor = cabeceras.get(nombre, "")
        # Google manda x-goog-authuser: 0 para la cuenta por defecto, que es
        # todas las cuentas del mundo y por lo tanto no identifica ninguna.
        util = valor and valor != "0"
        if util and encontrado is None:
            encontrado = f"cuenta:{valor}"
    return encontrado


def _de_una_credencial(cabeceras: dict[str, str]) -> str | None:
    """La huella del material de autenticacion, si lo hay."""

    encontrado = None
    for nombre in CABECERAS_DE_CREDENCIAL:
        valor = cabeceras.get(nombre, "")
        # "Bearer " delante no distingue nada y cambia entre clientes: se saca
        # para que la misma llave no de dos huellas distintas segun quien la
        # mande.
        limpio = re.sub(r"^(?:bearer|basic|token)\s+", "", valor, flags=re.IGNORECASE)
        if limpio and encontrado is None:
            encontrado = f"clave:{huella(limpio)}"
    return encontrado


def _de_la_ruta(path: str) -> str | None:
    match = _ORGANIZACION_EN_RUTA.search(path or "")
    return f"cuenta:{match.group(1)}" if match else None


def identidad(cabeceras: Any, path: str = "") -> str | None:
    """Que cuenta abrio este request, o None si el request no lo dice.

    El orden es por calidad de la senal y no por comodidad: un identificador de
    organizacion nombra a la empresa; una huella de credencial solo distingue a
    una llave de otra. Las dos sirven para comparar, pero la primera sobrevive a
    una rotacion de llaves y la segunda no.
    """

    normalizadas = _normalizadas(cabeceras)
    resultado = _de_una_cuenta(normalizadas)
    if resultado is None:
        resultado = _de_la_ruta(path)
    if resultado is None:
        resultado = _de_una_credencial(normalizadas)
    return resultado


def veredicto(quien: str | None, declaradas: frozenset[str]) -> str:
    """Si la cuenta es de la empresa, es de otro, o el request no lo dijo.

    Sin cuentas declaradas la respuesta es siempre SIN_IDENTIDAD, y no AJENA:
    una empresa que todavia no configuro nada no puede quedar bloqueada contra
    si misma. La comprobacion se enciende declarando, nunca por omision.
    """

    if not declaradas or quien is None:
        resultado = SIN_IDENTIDAD
    else:
        resultado = CORPORATIVA if quien in declaradas else AJENA
    return resultado


def es_ajena(cabeceras: Any, path: str, declaradas: frozenset[str]) -> str | None:
    """La identidad de la cuenta si es ajena a la empresa, o None.

    Devuelve la identidad y no un booleano porque quien llama la necesita para
    el evento: sin ella el panel dice "cuenta no autorizada" y nadie puede
    averiguar cual era.
    """

    quien = identidad(cabeceras, path)
    return quien if veredicto(quien, declaradas) == AJENA else None
