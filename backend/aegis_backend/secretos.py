"""De donde sale una API key, y de donde NO.

El backend necesita una credencial de modelo para dos cosas: clasificar dominios
y escribir lecciones. Esa credencial no puede vivir en el repositorio ni en una
variable de entorno de usuario.

En el repositorio es obvio. La variable de usuario tiene un problema menos
obvio y mas molesto: `ANTHROPIC_API_KEY` puesta a nivel de usuario se la come
cualquier proceso de la maquina, incluidos los CLI de IA, que cambian su forma
de autenticarse cuando la encuentran. Poner la clave del backend ahi le cambia
la sesion (y la facturacion) a quien este trabajando en ese equipo.

Asi que el orden es: la variable de entorno del PROCESO si alguien la puso a
proposito, y si no, un archivo fuera del repositorio.
"""

from __future__ import annotations

import os
from pathlib import Path

ARCHIVO_POR_DEFECTO = Path.home() / ".aegis" / "secretos.env"


def _del_archivo(nombre: str, ruta: Path) -> str:
    """Lee NOMBRE=valor de un archivo tipo .env. Cadena vacia si no esta.

    Nunca lanza: un backend sin clave sigue funcionando (clasifica con
    heuristica y sirve las lecciones escritas a mano), y quedarse sin arrancar
    por un archivo ilegible seria peor que quedarse sin modelo.
    """

    valor = ""
    try:
        if ruta.exists():
            for linea in ruta.read_text(encoding="utf-8").splitlines():
                limpia = linea.strip()
                if limpia and not limpia.startswith("#") and "=" in limpia:
                    clave, _, resto = limpia.partition("=")
                    if clave.strip() == nombre:
                        valor = resto.strip().strip("\"'")
    except OSError:
        valor = ""
    return valor


def cargar(nombre: str, ruta: Path | None = None) -> str:
    """La credencial, del entorno del proceso o del archivo. Cadena vacia si no hay."""

    del_entorno = os.environ.get(nombre, "").strip()
    return del_entorno or _del_archivo(nombre, ruta or ARCHIVO_POR_DEFECTO)


def hay(nombre: str, ruta: Path | None = None) -> bool:
    return bool(cargar(nombre, ruta))
