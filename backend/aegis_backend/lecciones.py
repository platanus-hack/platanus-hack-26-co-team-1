"""La leccion que ve la persona cuando Aegis le corta un envio.

Esta es la tesis del producto: un bloqueo que no ensena nada solo entrena a la
gente a buscar la forma de esquivarlo. Hasta aca las lecciones estaban escritas
a mano, una por regla, y por lo tanto decian lo mismo para todo el mundo.

La restriccion que hace interesante este archivo es el ADR 0003: **el contenido
no cruza la frontera**. O sea que la leccion hay que escribirla sin haber visto
nunca el dato. Lo unico que se tiene es la descripcion del hallazgo: que regla
salto, de que categoria, hacia donde iba y de que area es la persona.

Resulta que alcanza, y que es mejor asi: la leccion habla del TIPO de error, que
es lo que se puede corregir, y no del texto puntual, que la persona ya tiene
delante.

Como se sostiene esa frontera, en concreto:

  1. El prompt se arma desde una LISTA BLANCA de campos. Una lista negra se
     rompe sola: el dia que el agente agregue un campo nuevo al evento, viajaria
     sin que nadie lo decida. Aca, un campo que no este en la lista no existe.
  2. La evidencia ya viene redactada por el agente, y aun asi se recorta.
  3. Si el modelo no esta disponible, queda la leccion escrita a mano. Un
     backend sin modelo ensena menos, pero no deja de ensenar.
"""

from __future__ import annotations

import json

# Cuanto de la evidencia (ya redactada) se le muestra al modelo. Con el tipo de
# secreto alcanza para escribir la leccion; el valor no aporta nada.
EVIDENCIA_MAX = 24

MAX_REINTENTOS_DE_PARSEO = 1

# Lo unico que el modelo llega a ver. Todo lo demas del evento se descarta antes
# de armar el prompt, incluido cualquier campo que no este nombrado aca.
_CAMPOS = (
    "rule_id",
    "category",
    "severity",
    "engine",
    "evidence",
    "domain",
    "classification",
    "area",
    "action",
    "repeticiones",
)

_INSTRUCCIONES = """Sos el que le explica a un empleado por que su envio a una IA quedo frenado.

NO tenes el texto que la persona escribio, y no lo necesitas: no lo pidas, no lo
inventes y no digas que no lo tenes. Solo sabes que TIPO de dato se detecto.

Escribi para alguien que estaba haciendo su trabajo, no para un sospechoso. Sin
reto, sin alarma, sin mayusculas. La persona tiene que terminar de leer sabiendo
que hacer para seguir con lo suyo en los proximos treinta segundos.

Reglas de forma:
- title: una frase, maximo 70 caracteres. Que diga el riesgo concreto, no
  "cuidado con los datos sensibles".
- why: dos o tres oraciones. Por que ESE tipo de dato importa, en consecuencias
  reales para la empresa o para la persona.
- what_to_do: dos o tres oraciones, en imperativo, con la alternativa concreta
  que le permite seguir trabajando. Si el dato ya salio antes, deci que hacer al
  respecto.

Contesta UNICAMENTE con un objeto JSON con las claves title, why y what_to_do.
Sin texto antes ni despues, sin bloque de codigo."""


def _dato(evento: dict, peticion: dict) -> dict:
    """Aplana el evento a la lista blanca. Lo que no este aca, no viaja."""

    deteccion = evento.get("detection") or {}
    destino = evento.get("destination") or {}
    actor = evento.get("actor") or {}

    crudo = {
        "rule_id": deteccion.get("rule_id"),
        "category": deteccion.get("category"),
        "severity": deteccion.get("severity"),
        "engine": deteccion.get("engine"),
        "evidence": str(deteccion.get("evidence") or "")[:EVIDENCIA_MAX],
        "domain": destino.get("domain"),
        "classification": destino.get("classification"),
        "area": actor.get("area"),
        "action": evento.get("action"),
        "repeticiones": peticion.get("repeticiones"),
    }
    return {clave: crudo[clave] for clave in _CAMPOS if crudo.get(clave)}


def clave_de_cache(dato: dict) -> tuple:
    """Que hace unica a una leccion.

    No entra ni el event_id ni la persona: dos empleados a los que se les corta
    la misma regla hacia el mismo tipo de destino merecen la misma leccion, y
    generarla dos veces es pagar dos veces por el mismo texto. La reincidencia si
    entra, porque cambia lo que hay que decir.
    """

    repeticiones = dato.get("repeticiones") or 0
    reincide = "reincide" if int(repeticiones) > 2 else "primera"
    return (
        dato.get("rule_id"),
        dato.get("classification"),
        dato.get("area"),
        reincide,
    )


def _prompt(dato: dict) -> str:
    hechos = json.dumps(dato, ensure_ascii=False, indent=2)
    return f"{_INSTRUCCIONES}\n\nEsto es todo lo que se sabe del incidente:\n{hechos}"


def _parsear(crudo: str) -> dict | None:
    """Saca el JSON de la respuesta, tolerando que venga envuelto en prosa."""

    leccion = None
    try:
        inicio = crudo.index("{")
        fin = crudo.rindex("}") + 1
        candidato = json.loads(crudo[inicio:fin])
        if all(isinstance(candidato.get(k), str) and candidato[k].strip()
               for k in ("title", "why", "what_to_do")):
            leccion = {
                "title": candidato["title"].strip(),
                "why": candidato["why"].strip(),
                "what_to_do": candidato["what_to_do"].strip(),
            }
    except (ValueError, AttributeError, TypeError):
        leccion = None
    return leccion


RESPALDO = {
    "title": "Esta informacion no deberia salir de la empresa",
    "why": (
        "El envio quedo frenado porque contenia un dato que la politica de la "
        "empresa no deja salir hacia un servicio de IA."
    ),
    "what_to_do": (
        "Quitalo del texto y volve a intentar. Si necesitas que la IA trabaje "
        "sobre eso, reemplazalo por un valor de ejemplo."
    ),
}


def generar(peticion: dict, ask_model=None, cache: dict | None = None) -> dict:
    """La leccion para un evento redactado.

    Nunca lanza y nunca demora indefinidamente: si el modelo no esta, falla o
    contesta cualquier cosa, devuelve la leccion escrita a mano. Una leccion
    generica llega tarde; ninguna leccion rompe el producto.
    """

    evento = peticion.get("event") or peticion
    dato = _dato(evento, peticion)
    cache = cache if cache is not None else {}
    clave = clave_de_cache(dato)

    if clave in cache:
        leccion = dict(cache[clave])
        leccion["generada_por"] = "cache"
    else:
        leccion = None
        if ask_model is not None and dato.get("rule_id"):
            try:
                leccion = _parsear(ask_model(_prompt(dato)))
            except Exception:
                # Sin red, sin cuota o con una respuesta rara: queda el respaldo.
                # El backend no puede caerse por el servicio de otro.
                leccion = None
        if leccion is None:
            leccion = dict(RESPALDO)
            leccion["generada_por"] = "estatica"
        else:
            cache[clave] = dict(leccion)
            leccion["generada_por"] = "modelo"

    leccion["event_id"] = evento.get("event_id")
    leccion["rule_id"] = dato.get("rule_id")
    return leccion
