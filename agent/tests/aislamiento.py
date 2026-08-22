"""Aislamiento para los tests que construyen el addon de verdad.

`Aegis()` no es un objeto inerte. Al construirse hace tres cosas que salen de
su propio proceso:

  1. lee la politica de `~/.aegis/politica.json`, el HOME de quien corre la suite,
  2. le pide al backend una copia nueva por la red y la ESCRIBE en ese archivo,
  3. levanta el sensor de puntos ciegos, que mira la tabla de conexiones del
     sistema entero.

Un test que lo construye sin aislar depende de lo que haya levantado en la
maquina, y ademas le pisa al desarrollador su politica real.

Esto ya paso y costo veintitres tests rojos. La suite escribia
`~/.aegis/politica.json` con lo que servia un backend de desarrollo en :8686, y
despues los e2e leian ese archivo y obedecian el `equilibrado` que traia,
ignorando el `AEGIS_MODO=estricto` que ellos mismos ponian. En una maquina sin
backend levantado la suite pasaba entera: el peor tipo de acoplamiento, el que
solo se ve en la maquina equivocada.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


@contextmanager
def entorno_aislado(workdir: str | Path):
    """Deja el entorno listo para construir un `Aegis()` que no toque nada afuera.

    La politica va a un archivo de `workdir` (que no existe, asi que se usan los
    defaults), el backend queda apagado y el sensor tambien: los tres son
    efectos de red o de sistema que ningun test unitario deberia disparar.
    """

    with patch.dict(
        os.environ,
        {
            "AEGIS_POLITICA": str(Path(workdir) / "politica.json"),
            "AEGIS_BACKEND_DISABLED": "1",
            "AEGIS_SENSOR": "0",
        },
    ):
        yield


def variables_aisladas(workdir: str | Path) -> dict[str, str]:
    """Lo mismo que `entorno_aislado`, para pasarle a un proceso hijo.

    Los e2e levantan un mitmdump aparte y no pueden parchear su entorno: lo
    reciben armado. El backend y el sensor los deciden ellos, asi que aca solo
    va lo que nunca deben heredar del HOME.
    """

    return {"AEGIS_POLITICA": str(Path(workdir) / "politica.json")}
