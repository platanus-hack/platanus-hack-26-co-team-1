"""Los insights pedagogicos que ve el admin en el panel general.

Un dashboard que solo cuenta bloqueos entrena a mirar el numero, no a entender
el patron. Esto toma lo que ya calcula `agent/aegis_agent/panel/metrics.py` -
totales, por area, por regla, por herramienta - y lo convierte en dos o tres
frases: que comportamiento es riesgoso, que area esta menos familiarizada con
las herramientas, y que hacer al respecto. Es la misma tesis que sostiene
`lecciones.py` (un bloqueo que no ensena nada solo entrena a evadirlo), aplicada
a la vista del admin en vez de a la del empleado: el panel tiene que empujar a
ensenar, no a vigilar.

El ADR 0003 se sostiene igual que en el resto del backend, pero mas estricto
todavia: aca no viaja NINGUN dato de una persona, ni siquiera un seudonimo.
`people_at_risk` y los reincidentes por nombre se quedan afuera del resumen a
proposito (ver `_resumen`). Un panel pensado para instalar cultura no puede
alimentarse con "quien" en particular reincide - eso es exactamente el reflejo
punitivo que el producto quiere evitar, y ademas no le hace falta al modelo
para hablar de areas y de patrones.
"""

from __future__ import annotations

import hashlib
import json

# Cuantas filas de cada ranking le llegan al modelo. Alcanza para ver el
# patron -el top es lo que importa- sin mandar un prompt cada vez mas largo a
# medida que crece la semana.
MAX_ITEMS = 8

_INSTRUCCIONES = """Sos un asesor de seguridad que trabaja DENTRO de la cultura de una empresa, no un auditor que la vigila desde afuera.

Vas a ver metricas AGREGADAS de una ventana de tiempo de un producto DLP: cuantos intentos de mandar informacion sensible a herramientas de IA se bloquearon o se advirtieron, por area, por tipo de dato y por herramienta. No hay nombres de personas ni el contenido de nada: eso nunca sale de la empresa, y no lo vas a ver aunque lo pidas.

Tu trabajo es escribir insights y estrategias con lentes PEDAGOGICOS, para prevenir futuros incidentes formando habitos, no castigando los que ya pasaron:

- El objetivo es que el equipo entienda POR QUE existen estas reglas y las adopte como habito propio, no que se sienta vigilado o senalado.
- Distingui "riesgoso" de "poco familiarizado": un area con varios bloqueos criticos tiene un problema de habito (usa la herramienta y comete el mismo error); un area casi sin actividad tiene un problema de adopcion (no conoce la alternativa aprobada, o no sabe que existe la politica). Cada uno pide una estrategia distinta.
- Nunca acuses a una persona, sugieras sancion, o pidas mas vigilancia o mas control. Habla de AREAS y de PATRONES, nunca de individuos - ni siquiera con un ID.
- Las estrategias tienen que ser concretas y accionables esta semana: una capacitacion corta, un ejemplo compartido en un canal, una charla de equipo, un ajuste de que herramienta esta aprobada. Nunca "concientizar mas" o "reforzar la seguridad" sin decir como.

Se breve: cada "detalle" son maximo dos o tres oraciones. Esto no es un informe, es lo que alguien lee en el panel en quince segundos.

Responde UNICAMENTE con un objeto JSON, sin texto antes ni despues ni bloque de codigo, con esta forma exacta:

{"resumen": "una frase que resume el estado de la ventana, en tono constructivo",
"insights": [{"titulo": "...", "detalle": "...", "foco": "un area o 'toda la empresa'", "tipo": "riesgo|adopcion"}],
"estrategias": [{"titulo": "...", "detalle": "...", "publico": "a quien va dirigida"}]}

Entre 2 y 4 insights, entre 2 y 4 estrategias. Si los numeros son bajos o estan en cero, decilo como una buena senal en vez de inventar un riesgo que los datos no muestran."""


def _resumen(metrics) -> dict:
    """Lo unico que el modelo llega a ver: agregados, nunca una persona.

    Lista blanca y no negra, por la misma razon que en `lecciones._dato`: un
    campo nuevo que se agregue a `Metrics` el dia de manana no viaja solo
    porque nadie se acordo de sacarlo de aca.
    """

    return {
        "total": metrics.total,
        "bloqueados": metrics.blocked,
        "advertidos": metrics.warned,
        "tasa_de_bloqueo": round(metrics.block_rate, 1),
        "por_severidad": metrics.by_severity,
        "por_categoria": metrics.by_category,
        "top_reglas": metrics.by_rule[:MAX_ITEMS],
        "por_destino": [list(fila) for fila in metrics.by_destination[:MAX_ITEMS]],
        "por_area": [list(fila) for fila in metrics.by_area[:MAX_ITEMS]],
        "por_herramienta": metrics.by_process[:MAX_ITEMS],
        "shadow_ai": metrics.shadow_domains[:MAX_ITEMS],
        "sin_catalogar": metrics.uncatalogued_domains[:MAX_ITEMS],
    }


def clave_de_cache(datos: dict) -> str:
    """Un hash del resumen: si la ventana no cambio, no se paga el modelo de nuevo."""

    return hashlib.sha256(json.dumps(datos, sort_keys=True).encode()).hexdigest()


def _prompt(datos: dict) -> str:
    hechos = json.dumps(datos, ensure_ascii=False, indent=2)
    return f"{_INSTRUCCIONES}\n\nEsta es la ventana de tiempo elegida:\n{hechos}"


def _item_valido(item, claves) -> bool:
    return isinstance(item, dict) and all(
        isinstance(item.get(k), str) and item[k].strip() for k in claves
    )


def _parsear(crudo: str) -> dict | None:
    """Saca el JSON de la respuesta, tolerando que venga envuelto en prosa."""

    resultado = None
    try:
        inicio = crudo.index("{")
        fin = crudo.rindex("}") + 1
        candidato = json.loads(crudo[inicio:fin])
        resumen = candidato.get("resumen")
        insights = [i for i in candidato.get("insights") or [] if _item_valido(i, ("titulo", "detalle"))]
        estrategias = [
            e for e in candidato.get("estrategias") or [] if _item_valido(e, ("titulo", "detalle"))
        ]
        if isinstance(resumen, str) and resumen.strip() and insights and estrategias:
            resultado = {"resumen": resumen.strip(), "insights": insights, "estrategias": estrategias}
    except (ValueError, AttributeError, TypeError):
        resultado = None
    return resultado


# Dos respaldos y no uno: fingir riesgo en una semana tranquila es tan enganoso
# como fingir calma en una semana con bloqueos. Cual se usa lo decide `datos`,
# nunca el modelo (que es justo lo que no esta disponible en este camino).
RESPALDO_SIN_DATOS = {
    "resumen": "Todavia no hay actividad suficiente en esta ventana para sacar un patron.",
    "insights": [
        {
            "titulo": "Sin incidentes registrados en este rango",
            "detalle": (
                "No es garantia de que no vaya a pasar nada, pero tampoco hay "
                "ninguna senal de un problema activo. Vale la pena volver a "
                "mirar con mas dias de datos adentro."
            ),
            "foco": "toda la empresa",
            "tipo": "adopcion",
        }
    ],
    "estrategias": [
        {
            "titulo": "Aprovechar la calma para instalar el habito",
            "detalle": (
                "Sin urgencia encima es el mejor momento para una charla corta "
                "sobre que hace Aegis y por que, antes de que haga falta "
                "explicarlo recien despues de un bloqueo."
            ),
            "publico": "todo el equipo",
        }
    ],
}

RESPALDO_CON_DATOS = {
    "resumen": "Hubo intentos de enviar informacion sensible a herramientas de IA en esta ventana; vale la pena revisarlos en equipo.",
    "insights": [
        {
            "titulo": "Conviene mirar los bloqueos por area, no en total",
            "detalle": (
                "El desglose de abajo muestra que areas concentran mas "
                "intentos. Antes de asumir descuido, vale la pena preguntar si "
                "esas areas conocen la alternativa aprobada para su trabajo."
            ),
            "foco": "toda la empresa",
            "tipo": "riesgo",
        }
    ],
    "estrategias": [
        {
            "titulo": "Compartir el patron, no el caso puntual",
            "detalle": (
                "Una charla de equipo sobre el TIPO de dato que mas se intento "
                "enviar -sin mencionar a nadie- suele bajar la reincidencia mas "
                "que un mensaje de bloqueo aislado."
            ),
            "publico": "el area con mas intentos",
        }
    ],
}


def generar(metrics, ask_model=None, cache: dict | None = None) -> dict:
    """Los insights de una ventana de metricas.

    Nunca lanza y nunca deja el panel sin nada: si el modelo no esta configurado,
    falla, o contesta algo que no cierra como el JSON esperado, queda un
    respaldo escrito a mano. Cual de los dos depende de si hubo actividad o no,
    para no fingir riesgo ni fingir calma que los numeros no muestran.
    """

    datos = _resumen(metrics)
    cache = cache if cache is not None else {}
    clave = clave_de_cache(datos)

    if clave in cache:
        resultado = dict(cache[clave])
        resultado["generado_por"] = "cache"
    else:
        resultado = None
        if ask_model is not None:
            try:
                resultado = _parsear(ask_model(_prompt(datos)))
            except Exception:
                # Sin red, sin cuota o con una respuesta que no cerro como JSON:
                # el panel no puede quedarse sin insights por un problema ajeno.
                resultado = None
        if resultado is None:
            resultado = dict(RESPALDO_CON_DATOS if datos["total"] else RESPALDO_SIN_DATOS)
            resultado["generado_por"] = "estatico"
        else:
            cache[clave] = dict(resultado)
            resultado["generado_por"] = "modelo"

    return resultado
