from __future__ import annotations

from .suffixes import most_specific_match

# Cuando un host se confirma como IA, el proxy ya termino el handshake TLS y
# tiene su certificado en la mano: los SAN (Subject Alternative Names) casi
# siempre listan la familia entera del servicio -- chatgpt.com junto con
# chat.openai.com y api.openai.com -- sin que haga falta ni una consulta de
# red mas. Es la forma mas barata de descubrimiento que existe.
#
# El riesgo es un certificado de CDN compartida (Cloudflare, Fastly): ahi los
# SAN son de cientos de clientes sin relacion entre si, y tratarlos como
# "hermanos" ensuciaria la cola de investigacion con ruido. Dos guardas lo
# evitan: un tope a la cantidad de SAN, y que el CN corresponda de verdad al
# host que se esta mirando.

MAX_SAN = 20


def _normalizar(nombre: str) -> str:
    return nombre.lower().strip(".").removeprefix("*.")


def _cn_corresponde(cn: str, host: str) -> bool:
    """El CN es del host, o de un dominio que lo contiene."""

    limpio = _normalizar(cn)
    return most_specific_match(host, frozenset({limpio})) is not None


def hermanos(cn: str | None, host: str, altnames: list[str]) -> list[str]:
    """Dominios hermanos de `host` segun los SAN de su certificado TLS.

    Devuelve una lista vacia si el certificado no inspira confianza (demasiados
    SAN, o un CN que no corresponde al host) o si no hay nada que descubrir.
    No condena a los hermanos: se devuelven para que se encolen a investigar,
    igual que cualquier otro dominio nuevo.
    """

    host_normalizado = _normalizar(host)
    if not altnames or len(altnames) > MAX_SAN:
        resultado: list[str] = []
    else:
        if cn is not None and not _cn_corresponde(cn, host_normalizado):
            resultado = []
        else:
            limpios = {_normalizar(nombre) for nombre in altnames}
            resultado = sorted(
                nombre for nombre in limpios if nombre and nombre != host_normalizado
            )
    return resultado
