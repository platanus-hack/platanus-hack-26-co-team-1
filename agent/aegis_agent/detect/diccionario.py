"""Los datos que solo esta empresa sabe que son suyos.

Es la pieza que ningun detector generico puede tener, y por eso es la mas
precisa de todas. Una llave de AWS se reconoce por su formato y el modelo local
adivina que "Grupo Exito" es una empresa, pero **ninguno de los dos sabe que
Grupo Exito es cliente de esta empresa y que "Proyecto Fenix" es el nombre en
clave de la adquisicion que todavia no se anuncio**. Eso lo sabe la empresa, y
hasta aca no habia forma de que lo dijera.

Lo que la vuelve mejor que un modelo para este caso concreto:

  - Es determinista. Un termino declarado esta o no esta; no hay probabilidad
    que calibrar ni umbral que discutir.
  - No confunde mencionar con filtrar mejor que el modelo, pero cuando la
    empresa declara "Proyecto Fenix" ya tomo esa decision por su cuenta: no
    quiere que ese nombre salga, ni siquiera mencionado.
  - Cuesta microsegundos y no baja medio giga de pesos.

Lo que NO hace, y hay que decirlo: no generaliza. Si la empresa declara
"Bancolombia" y alguien escribe "Banco Colombia", esto no lo ve. Para eso esta
T2, que trabaja por sentido y no por texto. Las dos capas se complementan; la
que se cree que reemplaza a la otra es la que hace dano.

**El termino nunca sale del equipo.** Ni en la evidencia ni en el evento: viaja
la etiqueta que le puso la empresa ("cliente", "proyecto"), nunca el valor. El
diccionario es, por definicion, la lista mas sensible que tiene la empresa.
"""

from __future__ import annotations

import re
import unicodedata

from .types import Finding

# Por debajo de esto, un termino hace mas ruido que otra cosa. "SAP" o "IA"
# aparecen en cualquier conversacion y declararlos convierte al panel en un
# generador de falsos positivos.
LARGO_MINIMO = 4

# Tope de terminos por empresa. No es una limitacion tecnica: es que una lista
# mas larga que esto no la mantiene nadie y termina llena de terminos viejos que
# bloquean sin motivo.
MAX_TERMINOS = 500

_cache: dict[tuple, re.Pattern[str] | None] = {}


def sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _normalizar(texto: str) -> str:
    """Minusculas, sin tildes y con los espacios colapsados.

    Se compara asi de los dos lados. "Proyecto Fénix", "proyecto fenix" y
    "Proyecto  Fenix" son el mismo termino, y quien declara la lista no tendria
    por que acordarse de escribir las tres.
    """

    return re.sub(r"\s+", " ", sin_tildes(texto).lower()).strip()


def utilizables(terminos: dict[str, str]) -> dict[str, str]:
    """Los terminos que se pueden usar de verdad, ya normalizados.

    Descarta los cortos y recorta la lista. Que descarte en silencio es a
    proposito para el camino critico; la pantalla de politica es la que tiene
    que avisarle a quien lo escribio.
    """

    limpios: dict[str, str] = {}
    for termino, etiqueta in list(terminos.items())[:MAX_TERMINOS]:
        clave = _normalizar(str(termino))
        if len(clave) >= LARGO_MINIMO:
            limpios[clave] = str(etiqueta or "dato interno")
    return limpios


def _patron(terminos: dict[str, str]) -> re.Pattern[str] | None:
    """Una sola expresion regular con todos los terminos.

    Compilar una alternancia y no recorrer termino por termino: con doscientos
    terminos, la diferencia entre las dos formas es la diferencia entre estar en
    el camino critico y no estar.
    """

    clave = tuple(sorted(terminos))
    if clave not in _cache:
        if not terminos:
            _cache[clave] = None
        else:
            partes = "|".join(re.escape(t) for t in sorted(terminos, key=len, reverse=True))
            # El limite de palabra evita que "sura" marque "asegurar". Los
            # terminos de varias palabras entran igual porque \b mira los
            # extremos, no el medio.
            _cache[clave] = re.compile(rf"\b(?:{partes})\b")
    return _cache[clave]


def buscar(texto: str, terminos: dict[str, str]) -> list[Finding]:
    """Hallazgos del diccionario de la empresa. Lista vacia si no hay lista."""

    hallazgos: list[Finding] = []
    limpios = utilizables(terminos or {})
    patron = _patron(limpios)

    if patron is not None and texto:
        vistas: set[str] = set()
        for match in patron.finditer(_normalizar(texto)):
            etiqueta = limpios.get(match.group(0), "dato interno")
            if etiqueta not in vistas:
                vistas.add(etiqueta)
                hallazgos.append(
                    Finding(
                        rule_id=f"empresa_{_ruleid(etiqueta)}",
                        category="internal_data",
                        severity="high",
                        confidence=1.0,
                        # La etiqueta, nunca el termino. El diccionario es la
                        # lista mas sensible que tiene la empresa y no puede
                        # reconstruirse desde el panel.
                        evidence=f"<{etiqueta}>"[:32],
                        start=match.start(),
                        end=match.end(),
                    )
                )
    return hallazgos


def _ruleid(etiqueta: str) -> str:
    limpia = re.sub(r"[^a-z0-9]+", "_", _normalizar(etiqueta)).strip("_")
    return limpia or "dato_interno"
