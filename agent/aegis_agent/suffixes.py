from __future__ import annotations

from typing import Container

# La lista negra se pregunta en cada request que llega al proxy, y va a crecer
# sola con el tiempo: unos pocos dominios hoy, potencialmente miles con la base
# colaborativa en produccion. Un barrido de "cuales de todos los dominios
# matchean" es lineal en el tamano de la lista y se paga en cada peticion. Esto
# camina el host de mas especifico a menos y pregunta a lo sumo una vez por
# etiqueta: 3 o 4 lookups de hash, sin importar si la lista tiene 100 o 100000
# dominios.


def walk(host: str) -> list[str]:
    """Sufijos de `host`, del mas especifico al menos especifico.

    "api.chat.acme.com" camina como
    ["api.chat.acme.com", "chat.acme.com", "acme.com", "com"].

    Nunca corta a mitad de etiqueta: cada sufijo empieza justo despues de un
    punto, que es lo mismo que garantizaba el chequeo viejo con
    ``normalized.endswith("." + domain)``.
    """

    normalized = host.lower().strip(".")
    if normalized:
        labels = normalized.split(".")
        sufijos = [".".join(labels[i:]) for i in range(len(labels))]
    else:
        sufijos = []
    return sufijos


def most_specific_match(host: str, domains: Container[str]) -> str | None:
    """El sufijo mas especifico de `host` que esta en `domains`, o None.

    `domains` es cualquier contenedor con lookup O(1) por hash: un frozenset o
    un dict. Como se camina de mas a menos especifico, el primer sufijo que
    matchea ya es el mas largo posible.
    """

    match = None
    for sufijo in walk(host):
        if sufijo in domains:
            match = sufijo
            break
    return match
