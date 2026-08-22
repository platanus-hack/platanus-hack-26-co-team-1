"""Mide el nivel T2 contra un corpus en espanol.

El criterio de aceptacion mas duro no es cuanto detecta sino cuanto NO detecta:
un T2 ruidoso es peor que no tener T2, porque ensena a la gente a ignorar los
avisos. Por eso los falsos positivos se reportan primero.

    AEGIS_T2=1 python -m bench.evaluar_modelo
    AEGIS_T2=1 python -m bench.evaluar_modelo --umbrales 0.5,0.6,0.75
"""

from __future__ import annotations

import os
import statistics
import sys
import time

os.environ.setdefault("AEGIS_T2", "1")

from aegis_agent.detect import model  # noqa: E402
from aegis_agent.detect.engine import scan  # noqa: E402

# Casos que las reglas no pueden ver porque no tienen formato, tienen sentido.
SENSIBLE = [
    "El cliente Bancolombia esta renegociando el contrato de nomina para 2027",
    "Ana Maria Gomez, historia clinica: diagnostico de diabetes tipo 2",
    "Adjunto el acuerdo con Grupo Exito, valor 4.500 millones de pesos",
    "Mi jefe Carlos Restrepo aprobo el despido de tres personas del area",
    "El paciente reporta dolor toracico y antecedentes de hipertension",
    "La propuesta para Ecopetrol cierra en 1.200 millones, no lo comentes",
    "Vive en la calle 93 numero 15-20, apartamento 502, Bogota",
]

# Trabajo cotidiano. Cada marca aca es una razon para desinstalar Aegis.
NORMAL = [
    "Ayudame a escribir el resumen de la reunion de manana en tres vinetas",
    "Como optimizo una consulta SQL con muchos joins?",
    "Dame diez ideas de copy para una campana de cafe de origen",
    "Explicame la diferencia entre un proxy y un firewall",
    "Traduci este parrafo al ingles, tono formal",
    "Que patron de diseno conviene para un sistema de notificaciones?",
    "Escribi una funcion en Python que ordene una lista de diccionarios",
    "Cual es la mejor forma de estructurar un README?",
    "Revisa la ortografia de este texto y sugerime un titulo mas corto",
    "Necesito un cronograma de tres semanas para migrar a la version nueva",
]


def _umbrales() -> list[float]:
    for indice, arg in enumerate(sys.argv):
        if arg == "--umbrales" and indice + 1 < len(sys.argv):
            return [float(x) for x in sys.argv[indice + 1].split(",")]
    return [0.5, 0.6, 0.75]


def main() -> int:
    if not model.disponible():
        print("gliner no esta instalado: pip install gliner")
        return 1

    print(f"Modelo: {model.estado()['modelo']}")
    inicio = time.perf_counter()
    if model.cargar() is None:
        print("No se pudo cargar el modelo.")
        return 1
    print(f"Carga: {time.perf_counter() - inicio:.1f}s\n")

    tiempos: list[float] = []
    print(f"{'umbral':>7}  {'detecta':>9}  {'falsos +':>9}  etiquetas que marcaron trabajo normal")
    for umbral in _umbrales():
        detectados = 0
        for texto in SENSIBLE:
            arranque = time.perf_counter()
            hallazgos = model.scan_model(texto, umbral=umbral)
            tiempos.append((time.perf_counter() - arranque) * 1000)
            if hallazgos:
                detectados += 1

        ruido: list[str] = []
        for texto in NORMAL:
            arranque = time.perf_counter()
            hallazgos = model.scan_model(texto, umbral=umbral)
            tiempos.append((time.perf_counter() - arranque) * 1000)
            ruido.extend(h.rule_id.replace("modelo:", "") for h in hallazgos)

        print(
            f"{umbral:>7}  {detectados:>4}/{len(SENSIBLE):<4}  "
            f"{len(ruido):>4}/{len(NORMAL):<4}  {sorted(set(ruido)) or ''}"
        )

    ordenados = sorted(tiempos)
    p95 = ordenados[max(0, int(len(ordenados) * 0.95) - 1)]
    print(
        f"\nLatencia p50 {statistics.median(tiempos):.0f} ms | p95 {p95:.0f} ms "
        f"| presupuesto {model.LATENCIA_MAXIMA_MS} ms"
    )

    print("\nQue ve cada nivel, con el umbral configurado:")
    for texto in SENSIBLE[:4]:
        t1 = [f.rule_id for f in scan(texto)]
        t2 = [f.rule_id.replace("modelo:", "") for f in model.scan_model(texto)]
        print(f"  T1 {str(t1 or '-'):12} T2 {str(t2 or '-'):28} {texto[:46]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
