"""Mide el costo del nivel T1 en el camino critico.

El presupuesto declarado es < 5 ms por payload inspeccionado. Este script existe
para que ese numero sea una medicion y no una promesa.

    python -m bench.latency
"""

from __future__ import annotations

import statistics
import time

from aegis_agent.detect import scan

REPEATS = 200

CLEAN_PROMPT = (
    "Necesito que me ayudes a armar el plan de contenidos de septiembre para "
    "redes. Somos una marca de cafe de origen y el tono es cercano pero sin "
    "informalidades. Dame diez ideas de post con su copy y un llamado a la accion."
)

DIRTY_PROMPT = (
    "Estoy conectando la API de Meta para la campana. Estas son las credenciales "
    "del ambiente de produccion:\n"
    "  META_TOKEN=EAAGm0PX4ZCpsBA1ZBxKZBZCZBZCZBZCZB\n"
    "  AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
    "  DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod\n"
    "Contacto de soporte: ana.gomez@acme.co\n"
    "Revisa si la integracion esta bien planteada."
)


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _measure(label: str, text: str) -> None:
    # Una pasada previa para no medir el costo de calentar los caches del regex.
    scan(text)

    samples: list[float] = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        findings = scan(text)
        samples.append((time.perf_counter() - started) * 1000)

    print(
        f"{label:<28} {len(text):>7} chars  "
        f"p50 {statistics.median(samples):6.3f} ms  "
        f"p95 {_percentile(samples, 0.95):6.3f} ms  "
        f"p99 {_percentile(samples, 0.99):6.3f} ms  "
        f"hallazgos: {len(findings)}"
    )


def main() -> None:
    print(f"Motor T1 - {REPEATS} corridas por caso\n")
    _measure("prompt limpio", CLEAN_PROMPT)
    _measure("prompt con credenciales", DIRTY_PROMPT)
    _measure("archivo mediano limpio", CLEAN_PROMPT * 40)
    _measure("archivo grande limpio", CLEAN_PROMPT * 200)
    _measure("archivo grande con secretos", (CLEAN_PROMPT * 100) + DIRTY_PROMPT)


if __name__ == "__main__":
    main()
