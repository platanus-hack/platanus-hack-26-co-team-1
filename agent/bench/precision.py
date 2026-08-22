"""La precision de T1, medida, y la linea base que el trinquete defiende.

    python -m bench.precision                 # el reporte
    python -m bench.precision --guardar       # y grabar la linea base

## Que numero es EL numero

No es "cuanto detecta". Es **la precision del corte**: de todos los envios que
Aegis frena, cuantos merecian frenarse.

    precision del corte = cortes correctos / cortes totales

Se elige ese y no el F1 por una razon asimetrica que ya esta escrita en el repo y
que conviene no perder de vista: un aviso equivocado cuesta atencion, un corte
equivocado cuesta el producto. La persona a la que Aegis le frena un envio
legitimo no presenta un ticket: busca la forma de sacarse Aegis de encima, y a
partir de ahi el recall real es cero. Por eso el objetivo del corte es precision
~1,0, y el recall se maximiza *debajo* de esa restriccion --que es exactamente lo
que hacen los dos niveles de autoridad del modelo.

La industria publica ~95% de precision y <5% de falsos positivos para el DLP con
capa de ML, contra 5-25% que le atribuye al DLP de solo patrones. Aegis es de
solo patrones en T1, asi que este numero es el que dice si esa comparacion nos
favorece o no.

## Las tres cosas que mide

1. **Precision del corte** -- el numero de arriba.
2. **Recall por familia** -- donde falla, no solo cuanto. Una fuga escapada de
   credenciales no vale lo mismo que una de correos.
3. **Falsos positivos, separados en dos** -- los que solo avisan y los que
   CORTAN. Mezclarlos esconde el unico que importa.

## Lo que este banco NO puede decir

Los positivos con formato del corpus generado los fabrica el mismo prefijo que
busca la regla: ahi la medicion es de regresion, no de cobertura. Esta explicado
en `corpus_generado.py` y hay que leerlo antes de citar un numero de aca.

Y los datos de empresa sin formato se reportan aparte, porque T1 no tiene como
verlos: no tienen formato, tienen sentido. Contarlos como fuga escapada de T1
seria medir mal a proposito. Son el territorio de T2 y del juez que falta.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

os.environ.setdefault("AEGIS_T2", "0")
os.environ.setdefault("AEGIS_BACKEND_DISABLED", "1")

from aegis_agent.detect.payload import scan_payload  # noqa: E402
from aegis_agent.policy import Policy, decidir_sobre  # noqa: E402
from bench import corpus  # noqa: E402
from bench.corpus_generado import construir  # noqa: E402

# La politica de verdad, no una copia de sus reglas. Cuando eran dos copias, el
# banco reportaba ocho bloqueos falsos que el proxy nunca hacia.
POLITICA = Policy()

# El destino con el que se mide. Una IA aprobada es el caso mas exigente para la
# precision: el destino no se corta, asi que todo corte viene del CONTENIDO, que
# es justo lo que se quiere medir.
DESTINO = "ai_approved"

LINEA_BASE = pathlib.Path(__file__).resolve().parent / "linea_base.json"


def _como_llega(texto: str) -> bytes:
    """El texto dentro del JSON de una conversacion, que es como viaja.

    Medir sobre el texto pelado da otro numero, y el proyecto ya se llevo esa
    sorpresa al reves: sobre el cuerpo crudo el modelo marcaba 8 de cada 10
    frases normales, porque los nombres de los parametros le daban entidades por
    todos lados.
    """

    return json.dumps(
        {"model": "claude-opus-4", "messages": [{"role": "user", "content": texto}]}
    ).encode("utf-8")


def _decidir(texto: str) -> tuple[str, list]:
    resultado = scan_payload(_como_llega(texto))
    accion = decidir_sobre(DESTINO, resultado.findings, POLITICA)
    return accion, resultado.findings


def _texto(caso) -> str:
    return caso[0] if isinstance(caso, tuple) else caso


# Los positivos, agrupados por familia. El valor es (casos, corta_o_avisa), donde
# corta_o_avisa dice que se espera: hay familias que solo tienen que ADVERTIR.
def _familias_positivas(generado: dict) -> dict[str, tuple[list, str]]:
    return {
        "secretos con formato": (generado["secretos_con_formato"], "block_content"),
        "credenciales en espanol": (
            generado["credenciales_en_espanol"] + list(corpus.CREDENCIALES),
            "block_content",
        ),
        "documentos de identidad": (generado["documentos_de_identidad"], "warn"),
        "exports y volcados": (generado["exports"], "block_content"),
    }


def _negativos(generado: dict) -> list[str]:
    return list(generado["negativos"]) + list(corpus.NORMAL)


def medir() -> dict:
    generado = construir()
    familias = _familias_positivas(generado)
    negativos = _negativos(generado)

    reporte: dict = {"familias": {}, "negativos": {}, "sin_formato": {}}

    # --- positivos ----------------------------------------------------------
    cortes_correctos = 0
    for nombre, (casos, esperado) in familias.items():
        detectados = 0
        cortados = 0
        escapados: list[str] = []
        for caso in casos:
            texto = _texto(caso)
            accion, hallazgos = _decidir(texto)
            if hallazgos:
                detectados += 1
            else:
                escapados.append(texto)
            if accion == "block_content":
                cortados += 1
        if esperado == "block_content":
            cortes_correctos += cortados
        reporte["familias"][nombre] = {
            "total": len(casos),
            "detectados": detectados,
            "cortados": cortados,
            "esperado": esperado,
            "escapados": escapados[:5],
        }

    # --- negativos: la mitad donde esta la ciencia ---------------------------
    fp_avisan: list[str] = []
    fp_cortan: list[str] = []
    for texto in negativos:
        accion, hallazgos = _decidir(texto)
        if accion == "block_content":
            fp_cortan.append(texto)
        elif hallazgos:
            fp_avisan.append(texto)
    reporte["negativos"] = {
        "total": len(negativos),
        "fp_que_cortan": len(fp_cortan),
        "fp_que_avisan": len(fp_avisan),
        "ejemplos_que_cortan": fp_cortan[:10],
        "ejemplos_que_avisan": fp_avisan[:10],
    }

    # --- lo que T1 no puede ver: se reporta, no se le cobra -----------------
    # Los datos de salud y los domicilios van aca y no arriba: T1 no tiene como
    # verlos --"el paciente reporta dolor toracico" no tiene formato-- y
    # contarlos como fuga escapada de T1 seria medir mal a proposito. Estuvieron
    # un rato en el grupo de positivos y el reporte decia 0/8, que se lee como un
    # fallo y no lo es.
    sin_formato = (
        generado["datos_de_empresa"] + list(corpus.EMPRESA) + list(corpus.PERSONALES)
    )
    vistos = sum(1 for t in sin_formato if _decidir(t)[1])
    reporte["sin_formato"] = {
        "total": len(sin_formato),
        "vistos_por_t1": vistos,
        "nota": "T1 no tiene como verlos: no tienen formato, tienen sentido. "
        "Es el territorio de T2 y del juez que falta.",
    }

    # --- el numero ----------------------------------------------------------
    cortes_totales = cortes_correctos + len(fp_cortan)
    reporte["precision_del_corte"] = (
        round(cortes_correctos / cortes_totales, 4) if cortes_totales else 1.0
    )
    reporte["tasa_fp_que_corta"] = round(len(fp_cortan) / len(negativos), 4)
    reporte["tasa_fp_total"] = round(
        (len(fp_cortan) + len(fp_avisan)) / len(negativos), 4
    )
    reporte["casos"] = sum(len(c) for c, _ in familias.values()) + len(negativos) + len(
        sin_formato
    )
    return reporte


def imprimir(r: dict) -> None:
    print(f"\nCorpus: {r['casos']} casos\n")
    print(f"{'familia':28} {'total':>6} {'detecta':>8} {'corta':>7}  esperado")
    print("-" * 72)
    for nombre, d in r["familias"].items():
        print(
            f"{nombre:28} {d['total']:>6} {d['detectados']:>8} {d['cortados']:>7}"
            f"  {d['esperado']}"
        )
        for escapado in d["escapados"]:
            print(f"{'':30} escapo: {escapado[:70]}")

    n = r["negativos"]
    print(f"\nNegativos duros: {n['total']}")
    print(f"  falsos positivos que CORTAN : {n['fp_que_cortan']}")
    print(f"  falsos positivos que avisan : {n['fp_que_avisan']}")
    for ejemplo in n["ejemplos_que_cortan"]:
        print(f"    corta: {ejemplo[:80]}")
    for ejemplo in n["ejemplos_que_avisan"]:
        print(f"    avisa: {ejemplo[:80]}")

    s = r["sin_formato"]
    print(f"\nSin formato (no le toca a T1): {s['vistos_por_t1']}/{s['total']} vistos")

    print(f"\n{'=' * 72}")
    print(f"  PRECISION DEL CORTE      {r['precision_del_corte']:.2%}")
    print(f"  tasa de FP que corta     {r['tasa_fp_que_corta']:.2%}")
    print(f"  tasa de FP total         {r['tasa_fp_total']:.2%}")
    print(f"{'=' * 72}\n")


def guardar(r: dict) -> None:
    """Graba la linea base que defiende el trinquete.

    Se graban solo los agregados y no los ejemplos: los ejemplos son para leer, y
    meterlos en la linea base la volveria un archivo que cambia por cualquier
    cosa. Un trinquete que se actualiza seguido deja de trinquetar.
    """

    base = {
        "precision_del_corte": r["precision_del_corte"],
        "tasa_fp_que_corta": r["tasa_fp_que_corta"],
        "tasa_fp_total": r["tasa_fp_total"],
        "casos": r["casos"],
        "recall": {
            nombre: {"total": d["total"], "detectados": d["detectados"]}
            for nombre, d in r["familias"].items()
        },
    }
    LINEA_BASE.write_text(
        json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"linea base grabada en {LINEA_BASE}")


def main() -> int:
    reporte = medir()
    imprimir(reporte)
    if "--guardar" in sys.argv:
        guardar(reporte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
