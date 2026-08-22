"""Compara modelos candidatos para T2 sobre el mismo corpus.

Existe para contestar con datos una pregunta que se contesta sola con opiniones:
si conviene cambiar de modelo, achicarlo, o afinar uno propio.

Lo que mide, por modelo:

  detecta       cuantas frases sensibles marca (mas es mejor)
  bloquea mal   cuantas frases de trabajo normal CORTA (cero, o no sirve)
  avisa de mas  cuantas marca sin cortar (cuesta atencion, no trabajo)
  latencia      p50 y p95 contra el presupuesto de 700 ms
  peso          lo que hay que bajar e instalar en cada equipo

El peso es un criterio de producto, no una curiosidad: esto se instala en el
computador de cada empleado. Un modelo el doble de bueno que pese tres veces
mas puede ser la decision equivocada.

    AEGIS_T2=1 python -m bench.comparar_modelos
    AEGIS_T2=1 python -m bench.comparar_modelos --modelos urchade/gliner_small-v2.1
    AEGIS_T2=1 python -m bench.comparar_modelos --umbral 0.6
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("AEGIS_T2", "1")

from aegis_agent.detect import model  # noqa: E402
from aegis_agent.policy import Policy  # noqa: E402
from bench.corpus import GRUPOS_SENSIBLES, NORMAL, SENSIBLE  # noqa: E402

# Los candidatos, y por que cada uno esta en la lista:
#
#   gliner_multi-v2.1     el que corre hoy. Multilingue, la referencia.
#   gliner_multi_pii-v1   mismo tamano, pero afinado sobre datos personales.
#                         Es la hipotesis obvia: un modelo entrenado para esto
#                         deberia ganarle a uno de proposito general.
#   gliner_medium-v2.1    mas chico. La pregunta de si el tamano hace falta.
#   gliner_small-v2.1     el mas chico de la familia. El limite de cuanto se
#                         puede achicar antes de que deje de servir.
CANDIDATOS = (
    "urchade/gliner_multi-v2.1",
    "urchade/gliner_multi_pii-v1",
    "urchade/gliner_medium-v2.1",
    "urchade/gliner_small-v2.1",
)

POLITICA = Policy()


def _arg(nombre: str) -> str | None:
    for indice, valor in enumerate(sys.argv):
        if valor == nombre and indice + 1 < len(sys.argv):
            return sys.argv[indice + 1]
    return None


def _peso_en_disco(nombre: str) -> str:
    """Lo que ocupa el modelo en la cache de Hugging Face, en MB."""

    carpeta = Path.home() / ".cache" / "huggingface" / "hub"
    carpeta = carpeta / ("models--" + nombre.replace("/", "--"))
    resultado = "?"
    if carpeta.exists():
        # Los blobs son los pesos de verdad; el resto son enlaces y metadatos.
        total = sum(f.stat().st_size for f in carpeta.rglob("*") if f.is_file())
        resultado = f"{total / 1e6:.0f} MB"
    return resultado


def _cargar(nombre: str):
    """Carga un modelo puntual, sin pasar por la cache global del agente."""

    from gliner import GLiNER

    cargado = GLiNER.from_pretrained(nombre)
    model._modelo = cargado
    model._cargado = True
    return cargado


def _mirar(texto: str, umbral: float) -> tuple[bool, bool, float]:
    """(corta, marca, milisegundos) para una frase, con la politica de verdad."""

    arranque = time.perf_counter()
    hallazgos = model.scan_model(texto, umbral=umbral)
    transcurrido = (time.perf_counter() - arranque) * 1000
    corta = any(
        hallazgo.category in POLITICA.model_block_categories
        and model.etiqueta_de(hallazgo.rule_id) in POLITICA.model_block_labels
        for hallazgo in hallazgos
    )
    return corta, bool(hallazgos), transcurrido


def _medir(nombre: str, umbral: float) -> dict | None:
    print(f"\n--- {nombre}")
    inicio = time.perf_counter()
    try:
        _cargar(nombre)
    except Exception as error:  # noqa: BLE001  (cualquier fallo es "no sirve")
        print(f"    no se pudo cargar: {type(error).__name__}: {error}")
        return None
    carga = time.perf_counter() - inicio
    print(f"    carga {carga:.0f}s, peso {_peso_en_disco(nombre)}")

    tiempos: list[float] = []
    detectados = 0
    por_grupo: dict[str, str] = {}
    for grupo, frases in GRUPOS_SENSIBLES.items():
        aciertos = 0
        for frase in frases:
            _, marca, ms = _mirar(frase, umbral)
            tiempos.append(ms)
            aciertos += int(marca)
        detectados += aciertos
        por_grupo[grupo] = f"{aciertos}/{len(frases)}"

    bloqueos = 0
    avisos = 0
    for frase in NORMAL:
        corta, marca, ms = _mirar(frase, umbral)
        tiempos.append(ms)
        bloqueos += int(corta)
        avisos += int(marca and not corta)

    ordenados = sorted(tiempos)
    return {
        "nombre": nombre,
        "detecta": detectados,
        "bloquea": bloqueos,
        "avisa": avisos,
        "p50": statistics.median(tiempos),
        "p95": ordenados[min(len(ordenados) - 1, int(len(ordenados) * 0.95))],
        "carga": carga,
        "peso": _peso_en_disco(nombre),
        "grupos": por_grupo,
    }


def main() -> int:
    if not model.disponible():
        print("gliner no esta instalado: pip install -r requirements-modelo.txt")
        return 1

    umbral = float(_arg("--umbral") or model.UMBRAL_POR_DEFECTO)
    pedidos = _arg("--modelos")
    candidatos = tuple(pedidos.split(",")) if pedidos else CANDIDATOS

    print(f"Corpus: {len(SENSIBLE)} sensibles, {len(NORMAL)} de trabajo normal")
    print(f"Umbral: {umbral}  |  etiquetas: {len(POLITICA.model_labels)}")

    filas = [fila for nombre in candidatos if (fila := _medir(nombre, umbral))]

    print(f"\n{'modelo':<32} {'detecta':>9} {'bloq.mal':>9} {'avisa+':>8} "
          f"{'p50':>7} {'p95':>7} {'peso':>9}")
    for fila in filas:
        print(
            f"{fila['nombre']:<32} {fila['detecta']:>4}/{len(SENSIBLE):<4} "
            f"{fila['bloquea']:>4}/{len(NORMAL):<4} {fila['avisa']:>3}/{len(NORMAL):<4} "
            f"{fila['p50']:>6.0f}m {fila['p95']:>6.0f}m {fila['peso']:>9}"
        )

    print("\nDetalle por grupo sensible:")
    grupos = list(GRUPOS_SENSIBLES)
    print(f"{'modelo':<32} " + " ".join(f"{g:>14}" for g in grupos))
    for fila in filas:
        print(
            f"{fila['nombre']:<32} "
            + " ".join(f"{fila['grupos'][g]:>14}" for g in grupos)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
