"""Las rutas del backend, sin el servidor que las sirve.

Hasta aca el backend colaborativo (dominios, politicas, lecciones) vivia dentro
de un HTTPServer propio en el puerto 8686, y el panel desplegado vivia en otro.
En produccion corria uno solo: `render.yaml` levanta `web/app.py` y nada mas, asi
que /v1/policy y /v1/domains simplemente **no existian** fuera de una maquina de
desarrollo. El agente pedia su politica al aire.

Sacar la logica del handler y dejarla en funciones sueltas es lo que permite que
los dos la sirvan sin copiarla. Y de paso desaparece la duplicacion que ya habia:
la frontera del ADR 0003 -que un evento no puede traer contenido- estaba escrita
dos veces, en dos archivos, con dos nombres. Una regla de seguridad copiada es
una regla que en algun momento se corrige en un solo lado.

Cada funcion devuelve `(estado, cuerpo)` y no toca la red: asi se prueban sin
levantar nada.
"""

from __future__ import annotations

import threading
import time

from . import lecciones
from .classifier import classify
from .store import DomainStore, vencido

CAMPOS_PROHIBIDOS = ("payload", "content", "text", "prompt", "body", "raw")
EVIDENCIA_MAX = 32

# La cola de clasificacion corre aparte del request que la disparo: el agente
# pregunta, recibe "todavia no se" al instante y sigue trabajando con su
# politica. Nadie espera a que un modelo se decida.
_pendientes: set[str] = set()
_candado = threading.Lock()


def lleva_contenido(evento: dict) -> bool:
    """La frontera del ADR 0003, revisada del lado que recibe.

    No alcanza con que el agente prometa no mandar contenido: el servicio que lo
    recibe tiene que poder rechazarlo, porque cualquiera puede escribir a este
    endpoint. Las tres condiciones cubren tres formas distintas de colarlo: un
    campo entero, una evidencia que dejo de ser una etiqueta y se volvio una
    cita, y una URL completa disfrazada de dominio.
    """

    evidencia = (evento.get("detection") or {}).get("evidence", "")
    destino = (evento.get("destination") or {}).get("domain", "")
    return (
        any(campo in evento for campo in CAMPOS_PROHIBIDOS)
        or len(evidencia) > EVIDENCIA_MAX
        or "/" in destino
    )


def politica_por_defecto() -> dict:
    """Lo que recibe un agente que todavia no tiene politica propia."""

    return {
        "policy_version": 1,
        "unknown_domain_action": "warn",
        "approved_ai": ["claude.ai", "api.anthropic.com"],
        "rules": {"secret": "block", "internal_data": "block", "pii": "warn"},
    }


def veredicto(domain: str, store: DomainStore, ask_model=None) -> tuple[int, dict]:
    """El veredicto de un dominio, o 202 mientras se averigua.

    Un veredicto vencido igual se manda, y la reclasificacion se encola aparte:
    el camino critico nunca se queda esperando, y un veredicto viejo siempre es
    mejor que ninguno.
    """

    domain = domain.split("?")[0].strip("/").lower()
    encontrado = store.get(domain)
    if encontrado is not None:
        if vencido(encontrado, time.time()):
            _encolar(domain, store, ask_model)
        respuesta = (200, encontrado.as_response())
    else:
        _encolar(domain, store, ask_model)
        respuesta = (202, {"domain": domain, "classification": "pending"})
    return respuesta


DESDE_EL_ORIGEN = "1970-01-01T00:00:00Z"


def sincronizacion(store: DomainStore, desde: str) -> tuple[int, dict]:
    """El delta que el agente baja para su cache local.

    La comparacion del camino critico (ver suffixes.py) nunca toca la base: el
    agente sincroniza de vez en cuando y compara en memoria. Sin `desde` se
    manda todo, que es lo que pide un agente en su primer arranque.
    """

    # Un `desde` vacio o ilegible es "desde el principio", que es justo lo que
    # pide un agente en su primer arranque. Se normaliza ACA y no en cada store
    # porque los dos leen la marca distinto: el de memoria la convierte a epoch
    # y el de Supabase la manda cruda dentro de un filtro PostgREST. Sin esto,
    # una marca vacia reventaba el de memoria y le armaba una consulta invalida
    # al otro -- y este endpoint es publico, asi que la marca la elige quien
    # llama.
    desde = desde.strip() or DESDE_EL_ORIGEN
    ahora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return (200, {"dominios": [v.as_response() for v in store.desde(desde)], "hasta": ahora})


def _encolar(domain: str, store: DomainStore, ask_model) -> None:
    with _candado:
        nuevo = domain not in _pendientes
        if nuevo:
            _pendientes.add(domain)
    if nuevo:
        threading.Thread(
            target=_clasificar, args=(domain, store, ask_model), daemon=True
        ).start()


def _clasificar(domain: str, store: DomainStore, ask_model) -> None:
    try:
        store.put(classify(domain, ask_model))
    finally:
        with _candado:
            _pendientes.discard(domain)


def leccion(peticion: dict, ask_model, cache: dict) -> tuple[int, dict]:
    """La leccion que corresponde a un corte. Nunca necesita el contenido."""

    if lleva_contenido(peticion.get("event") or peticion):
        respuesta = (422, {"error": "el evento contiene campos prohibidos"})
    else:
        respuesta = (200, lecciones.generar(peticion, ask_model, cache))
    return respuesta
