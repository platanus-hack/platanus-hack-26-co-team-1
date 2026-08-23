"""Mide que comparar un host contra la lista negra no dependa de su tamano.

_match_length recorria todo el conjunto de dominios en cada request. Con la
caminata de sufijos (aegis_agent/suffixes.py) el costo es proporcional a la
cantidad de etiquetas del host, no al tamano de la lista: este script muestra
la diferencia entre una lista de 120 dominios (la semilla de hoy) y una de
10000 (lo que la base colaborativa puede acumular en produccion).

    python -m bench.lista_negra
"""

from __future__ import annotations

import statistics
import time

from aegis_agent.catalog import AI_DOMAINS
from aegis_agent.suffixes import most_specific_match

REPEATS = 5000

HOST_CATALOGADO = "copilot.microsoft.com"
HOST_DESCONOCIDO = "portal-interno-de-una-empresa-cualquiera.com.co"


def _lista_grande(tamano: int) -> frozenset[str]:
    generados = {f"servicio-generado-{i}.example.com" for i in range(tamano)}
    return frozenset(generados | AI_DOMAINS)


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _measure(label: str, host: str, dominios: frozenset[str]) -> None:
    most_specific_match(host, dominios)  # entrada en caliente

    samples: list[float] = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        most_specific_match(host, dominios)
        samples.append((time.perf_counter() - started) * 1_000_000)

    print(
        f"{label:<38} {len(dominios):>6} dominios  "
        f"p50 {statistics.median(samples):7.3f} us  "
        f"p99 {_percentile(samples, 0.99):7.3f} us"
    )


def main() -> None:
    print(f"Lookup en la lista negra - {REPEATS} corridas por caso\n")
    chica = frozenset(AI_DOMAINS)
    grande = _lista_grande(10_000)

    _measure("catalogado, lista de hoy (120)", HOST_CATALOGADO, chica)
    _measure("catalogado, lista de 10000", HOST_CATALOGADO, grande)
    _measure("desconocido, lista de hoy (120)", HOST_DESCONOCIDO, chica)
    _measure("desconocido, lista de 10000", HOST_DESCONOCIDO, grande)


if __name__ == "__main__":
    main()
