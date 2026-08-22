"""Validadores que necesitan mirar alrededor del match, no solo el valor.

Hay reglas cuyo falso positivo no se puede resolver mirando lo que casaron: hay
que mirar de que se estaba hablando. Dos casos, los dos medidos:

    «el numero de la factura es 4111111111111111»      -> credit_card
    «como configuro el confidencial en el pie de pagina?» -> confidentiality_marker

El segundo es un bloqueo: ``confidentiality_marker`` es ``internal_data``, y
``internal_data`` esta en ``block_categories``. Una pregunta de Word cortaba el
envio.

Estos validadores reciben el texto completo y las posiciones del match, asi que
pueden leer la ventana anterior. Es informacion que el detector ya tiene en la
mano: no agrega ninguna llamada ni ninguna dependencia.
"""

from __future__ import annotations

import re

# Cuanto se mira hacia atras. Corto a proposito: con una ventana larga, cualquier
# texto de oficina tiene la palabra "factura" en algun lado y la regla se apaga
# donde no debia.
VENTANA = 48


def _antes(text: str, start: int, ventana: int = VENTANA) -> str:
    return text[max(0, start - ventana) : start].lower()


# --- credit_card -------------------------------------------------------------
#
# Luhn valida el digito de control, no el hecho de ser una tarjeta. Un numero de
# factura, un consecutivo o una tira de telefonos pasan Luhn por casualidad: en
# la sonda, veinte telefonos colombianos en una lista se reportaron como
# credit_card, que es a la vez un falso positivo de categoria y un falso negativo
# de lo que en realidad era (un export de contactos).

_NO_ES_TARJETA = re.compile(
    r"(?:factura|facturas|orden|ordenes|pedido|pedidos|radicado|consecutivo"
    r"|remision|guia|referencia|recibo|comprobante|cotizacion|contrato"
    r"|expediente|ticket|folio|serie|imei|codigo de barras|ean|isbn"
    # Indicadores de telefono: el otro caso medido.
    r"|telefono|telefonos|tel|celular|celulares|movil|whatsapp|fijo"
    r"|\+\s?\d{1,3}\s?\d)"
)


def es_tarjeta_de_verdad(text: str, start: int, end: int) -> bool:
    """Descarta el numero que pasa Luhn pero no es una tarjeta."""

    return _NO_ES_TARJETA.search(_antes(text, start)) is None


# --- confidentiality_marker --------------------------------------------------
#
# Un documento se marca a si mismo: "CONFIDENCIAL" arriba, "uso interno" en el
# pie. Nadie escribe "confidencial" en el medio de una pregunta sobre como
# maquetar un documento. La senal que separa las dos cosas es que la frase sea
# una PREGUNTA o una consulta de "como hacer", que es lenguaje sobre la
# herramienta y no contenido de la empresa.

_ES_CONSULTA = re.compile(
    r"(?:\bcomo\b|\bcomo\s|\bque\s|\bdonde\b|\bcual\b|\bcuando\b"
    r"|configur|maquet|format|plantilla|ejemplo|tutorial|paso a paso"
    r"|pie de pagina|encabezado|marca de agua|membrete"
    r"|ayudame|explicame|ensename|sugerime|recomendame)"
)


def es_marca_de_documento(text: str, start: int, end: int) -> bool:
    """El marcador marca un documento, y no es una pregunta sobre marcadores.

    Se mira hacia atras Y hacia adelante hasta el final de la oracion, porque la
    palabra interrogativa puede estar en cualquiera de los dos lados:
    "como pongo el confidencial" y "el confidencial, como se configura".
    """

    cola = text[end : end + VENTANA].lower()
    hay_pregunta = "?" in cola or "?" in _antes(text, start)
    return not (
        hay_pregunta
        or _ES_CONSULTA.search(_antes(text, start)) is not None
        or _ES_CONSULTA.search(cola) is not None
    )
