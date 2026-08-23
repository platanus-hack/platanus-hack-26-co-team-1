from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from .policy import Policy

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
    return politica


def guardar(politica: Policy, ruta: Path | None = None) -> None:
    """Escritura atomica: nunca puede quedar un JSON truncado a mitad de escritura."""

    destino = _ruta(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")
    temporal.write_text(
        json.dumps(politica.a_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporal, destino)


def refrescar_ahora(
    url_base: str, tenant_id: str, ruta: Path | None = None
) -> Policy | None:
    """Pide la politica al backend, la persiste y la devuelve.

    Es el tick del hot-reload: quien la recibe puede aplicarla a la referencia
    viva sin esperar al proximo arranque. Nunca lanza: sin red, backend caido
    o respuesta invalida devuelve None y el disco (la ultima politica
    conocida) queda tal cual estaba.
    """

    try:
        peticion = urllib.request.Request(
            f"{url_base.rstrip('/')}/v1/policy/{tenant_id}"
        )
        with urllib.request.urlopen(peticion, timeout=REQUEST_TIMEOUT) as respuesta:
            if respuesta.status == 200:
                datos = json.loads(respuesta.read())
                if datos:
                    politica = Policy.desde_dict(datos)
                    guardar(politica, ruta)
                    return politica
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        pass
    return None


def refrescar_en_segundo_plano(
    url_base: str, tenant_id: str, ruta: Path | None = None
) -> threading.Thread:
    """Version un-solo-disparo de refrescar_ahora, en un hilo daemon.

    No devuelve la politica y no bloquea a nadie: el efecto es solo dejar el
    archivo listo para el proximo arranque.
    """

    hilo = threading.Thread(
        target=refrescar_ahora, args=(url_base, tenant_id, ruta), daemon=True
    )
    hilo.start()
    return hilo
