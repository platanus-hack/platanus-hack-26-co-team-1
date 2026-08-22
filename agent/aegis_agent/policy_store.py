from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import replace
from pathlib import Path

from .policy import Policy, modo_pedido_por_el_entorno

# Almacen local de la politica. Mismo patron que domains.py: el camino critico
# solo lee el disco, y la red actualiza el disco en segundo plano para la
# proxima vez. Ver ADR 0003: la decision de bloquear es 100% local y nunca
# puede esperar a la red.

RUTA_POR_DEFECTO = Path.home() / ".aegis" / "politica.json"

REQUEST_TIMEOUT = 5


def _ruta(ruta: Path | None) -> Path:
    # Se relee el entorno en cada llamada (y no solo al importar) para que un
    # test pueda apuntar a otro archivo sin recargar el modulo.
    return ruta if ruta is not None else Path(
        os.environ.get("AEGIS_POLITICA", str(RUTA_POR_DEFECTO))
    )


def cargar(ruta: Path | None = None) -> Policy:
    """La politica guardada, o los defaults si no hay nada confiable.

    Nunca lanza: un archivo ausente, corrupto o con un JSON invalido no puede
    dejar al agente sin politica. Se cae a Policy() en todos esos casos.
    """

    destino = _ruta(ruta)
    politica = Policy()
    try:
        if destino.exists():
            datos = json.loads(destino.read_text(encoding="utf-8") or "{}")
            politica = Policy.desde_dict(datos)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        politica = Policy()
    return _con_el_modo_del_entorno(politica)


def _con_el_modo_del_entorno(politica: Policy) -> Policy:
    """AEGIS_MODO, cuando esta puesta, le gana al archivo.

    La politica guardada es la de la empresa y llega del backend; AEGIS_MODO la
    pone quien instala el agente en ese equipo, y las dos tienen que poder
    convivir. Sin esta linea el interruptor que documenta OPERACION.md deja de
    existir apenas el agente cachea una politica por primera vez: el archivo
    trae el modo con el que se serializo y ya no hay forma de volver a estricto
    sin borrarlo a mano.
    """

    accion = modo_pedido_por_el_entorno()
    resultado = politica
    if accion is not None and accion != politica.unapproved_ai_action:
        resultado = replace(politica, unapproved_ai_action=accion)
    return resultado


def guardar(politica: Policy, ruta: Path | None = None) -> None:
    """Escritura atomica: nunca puede quedar un JSON truncado a mitad de escritura."""

    destino = _ruta(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    temporal.write_text(
        json.dumps(politica.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporal, destino)


def refrescar_en_segundo_plano(
    url_base: str, tenant_id: str, ruta: Path | None = None
) -> threading.Thread:
    """Pide la politica al backend y, si llega bien, la deja guardada.

    No devuelve nada y no bloquea a nadie: el efecto es solo dejar el archivo
    listo para el proximo arranque. Si el backend esta caido o la respuesta
    viene rara, se traga el error y la politica en disco queda como estaba.
    """

    def _tarea() -> None:
        try:
            peticion = urllib.request.Request(
                f"{url_base.rstrip('/')}/v1/policy/{tenant_id}"
            )
            with urllib.request.urlopen(peticion, timeout=REQUEST_TIMEOUT) as respuesta:
                if respuesta.status == 200:
                    datos = json.loads(respuesta.read())
                    if datos:
                        # Se mezcla sobre la politica que ya hay, no sobre los
                        # defaults: lo que el backend no nombra se conserva.
                        guardar(Policy.desde_dict(datos, cargar(ruta)), ruta)
        except (urllib.error.URLError, OSError, ValueError, TypeError):
            # Sin red, backend caido o respuesta invalida: la politica en
            # disco (la ultima conocida) queda tal cual estaba.
            pass

    hilo = threading.Thread(target=_tarea, daemon=True)
    hilo.start()
    return hilo
