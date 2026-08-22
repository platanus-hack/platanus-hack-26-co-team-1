"""Mide el nivel T2 contra el corpus en espanol y elige el umbral con datos.

El criterio de aceptacion mas duro no es cuanto detecta sino cuanto NO detecta.
Y dentro de eso, lo unico que realmente duele es lo que CORTA un envio legitimo:
un aviso se ignora, un bloqueo equivocado hace que la persona busque la forma de
sacarse Aegis de encima.

Por eso el reporte separa las dos cosas. Un falso positivo que solo avisa cuesta
atencion; uno que bloquea cuesta el producto.

    AEGIS_T2=1 python -m bench.evaluar_modelo
    AEGIS_T2=1 python -m bench.evaluar_modelo --umbrales 0.4,0.5,0.6,0.75
"""

from __future__ import annotations

import os
import statistics
import sys
import time

os.environ.setdefault("AEGIS_T2", "1")

from aegis_agent.detect import model  # noqa: E402
from aegis_agent.policy import Policy  # noqa: E402
from bench.corpus import GRUPOS_NORMALES, GRUPOS_SENSIBLES, NORMAL, SENSIBLE  # noqa: E402

# Se usa la politica de verdad y no una copia de sus reglas: un banco que mide
# algo distinto de lo que hace el proxy es peor que no tener banco, porque
# reporta en verde una configuracion que en produccion corta lo que no debe.
POLITICA = Policy()


def _umbrales() -> list[float]:
    for indice, arg in enumerate(sys.argv):
        if arg == "--umbrales" and indice + 1 < len(sys.argv):
            return [float(x) for x in sys.argv[indice + 1].split(",")]
    return [0.4, 0.5, 0.6, 0.75]


def _mirar(texto: str, umbral: float) -> tuple[bool, bool, float]:
    """Devuelve (corta, avisa, milisegundos) para una frase."""

    arranque = time.perf_counter()
    hallazgos = model.scan_model(texto, umbral=umbral)
    transcurrido = (time.perf_counter() - arranque) * 1000
    corta = any(
        hallazgo.category in POLITICA.model_block_categories
        and model.etiqueta_de(hallazgo.rule_id) in POLITICA.model_block_labels
        for hallazgo in hallazgos
    )
    return corta, bool(hallazgos), transcurrido


def main() -> int:
    if not model.disponible():
        print("gliner no esta instalado: pip install -r requirements-modelo.txt")
        return 1

    print(f"Modelo: {model.estado()['modelo']}")
    inicio = time.perf_counter()
    if model.cargar() is None:
        print("No se pudo cargar el modelo.")
        return 1
    print(f"Carga: {time.perf_counter() - inicio:.1f}s")
    print(f"Corpus: {len(SENSIBLE)} sensibles, {len(NORMAL)} de trabajo normal\n")

    tiempos: list[float] = []

    print(f"{'umbral':>7}  {'detecta':>9}  {'bloquea mal':>12}  {'avisa de mas':>13}")
    for umbral in _umbrales():
        detectados = 0
        for texto in SENSIBLE:
            _, avisa, ms = _mirar(texto, umbral)
            tiempos.append(ms)
            detectados += int(avisa)

        bloqueos_malos = 0
        avisos_de_mas = 0
        for texto in NORMAL:
            corta, avisa, ms = _mirar(texto, umbral)
            tiempos.append(ms)
            bloqueos_malos += int(corta)
            avisos_de_mas += int(avisa and not corta)

        print(
            f"{umbral:>7}  {detectados:>4}/{len(SENSIBLE):<4}  "
            f"{bloqueos_malos:>7}/{len(NORMAL):<4}  {avisos_de_mas:>8}/{len(NORMAL):<4}"
        )

    umbral_actual = model.UMBRAL_POR_DEFECTO
    print(f"\nDetalle por grupo en el umbral que esta configurado ({umbral_actual}):")
    for nombre, frases in GRUPOS_SENSIBLES.items():
        aciertos = sum(1 for f in frases if _mirar(f, umbral_actual)[1])
        print(f"   sensible  {nombre:<20} {aciertos}/{len(frases)}")
    for nombre, frases in GRUPOS_NORMALES.items():
        cortes = sum(1 for f in frases if _mirar(f, umbral_actual)[0])
        marcas = sum(1 for f in frases if _mirar(f, umbral_actual)[1])
        print(f"   normal    {nombre:<20} bloquea {cortes}/{len(frases)}, marca {marcas}/{len(frases)}")

    if tiempos:
        ordenados = sorted(tiempos)
        p95 = ordenados[int(len(ordenados) * 0.95) - 1]
        print(
            f"\nLatencia: p50 {statistics.median(tiempos):.0f} ms, p95 {p95:.0f} ms, "
            f"presupuesto {model.LATENCIA_MAXIMA_MS} ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
