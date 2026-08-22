from __future__ import annotations

import json

# Lo que se le da al modelo local no puede ser lo mismo que se le da a las reglas.
#
# T1 escanea el request entero a proposito: un secreto puede estar en una
# cabecera, en un campo de metadatos o en cualquier rincon del JSON, y una
# expresion regular lo encuentra igual de bien en todos.
#
# T2 es lo contrario. Es un extractor de entidades entrenado sobre lenguaje
# natural, y darle {"model":"gpt-4o","max_tokens":1024,"messages":[...]} lo
# obliga a buscar personas y empresas entre llaves, comillas y nombres de
# parametros. Aca se saca lo que la persona efectivamente escribio, que es sobre
# lo unico que ese modelo sabe opinar.

MAX_PROMPT_CHARS = 8000

# Un JSON de conversacion es plano; esta cota existe para que un cuerpo armado a
# proposito no haga trabajar de mas al que esta en el camino critico.
MAX_PROFUNDIDAD = 12

# Claves que llevan texto escrito por una persona. No estan "model",
# "temperature" ni "stream" a proposito: son configuracion de la llamada y solo
# le agregan ruido al modelo.
CLAVES_DE_TEXTO = frozenset(
    {
        "content",
        "text",
        "prompt",
        "input",
        "inputs",
        "query",
        "question",
        "system",
        "message",
        "instructions",
    }
)


def _cargar_json(texto: str) -> object | None:
    recorte = texto.lstrip()
    if recorte[:1] in ("{", "["):
        try:
            datos = json.loads(recorte)
        except (ValueError, RecursionError):
            datos = None
    else:
        datos = None
    return datos


def _de_json(nodo: object, profundidad: int = 0) -> list[str]:
    """Recorre el arbol juntando solo los valores de texto de una persona.

    Se recorre en vez de reconocer cada proveedor uno por uno porque las formas
    se parecen todas: el texto vive bajo las mismas claves aunque el envoltorio
    cambie, y una forma nueva no deberia necesitar un release.
    """

    partes: list[str] = []
    if profundidad <= MAX_PROFUNDIDAD:
        if isinstance(nodo, dict):
            for clave, valor in nodo.items():
                if isinstance(valor, str):
                    if clave.lower() in CLAVES_DE_TEXTO:
                        partes.append(valor)
                else:
                    partes.extend(_de_json(valor, profundidad + 1))
        else:
            if isinstance(nodo, list):
                for elemento in nodo:
                    partes.extend(_de_json(elemento, profundidad + 1))
    return partes


def _cuerpo_de_la_parte(bloque: str) -> str:
    for separador in ("\r\n\r\n", "\n\n"):
        _, encontrado, cuerpo = bloque.partition(separador)
        if encontrado:
            return cuerpo.strip()
    return ""


def _de_multipart(texto: str) -> list[str]:
    """Los campos de texto del formulario, nunca los adjuntos.

    Un archivo adjunto es trabajo de T1: sus firmas y su nombre dicen mas que
    cualquier entidad que un modelo de lenguaje pueda sacarle a un binario.
    """

    partes: list[str] = []
    primera = texto.lstrip().split("\n", 1)[0].strip()
    if primera.startswith("--") and "form-data" in texto:
        for bloque in texto.split(primera):
            if "form-data" in bloque and "filename=" not in bloque:
                cuerpo = _cuerpo_de_la_parte(bloque)
                if cuerpo:
                    partes.append(cuerpo)
    return partes


def extract_prompt(texto: str) -> str:
    """El texto que escribio la persona, o vacio si la forma no se reconoce.

    Devolver vacio no es un fallo: es la senal de que hay que mirar el cuerpo
    completo. El shadow AI que todavia no esta en ninguna lista tampoco tiene una
    forma conocida, y recortar ahi seria recortar justo el caso peligroso.
    """

    datos = _cargar_json(texto)
    if datos is None:
        partes = _de_multipart(texto)
    else:
        partes = _de_json(datos)
    return "\n".join(parte for parte in partes if parte.strip())[:MAX_PROMPT_CHARS]
