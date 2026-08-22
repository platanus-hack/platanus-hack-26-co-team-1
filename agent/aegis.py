"""Punto de entrada del ejecutable.

    python aegis.py estado          # desde el repo
    Aegis.exe estado                # empaquetado

Este archivo existe por la misma razon que `aegis_mitm.py`, y vale la pena decirlo
porque es el mismo error dos veces con dos cargadores distintos:

**PyInstaller ejecuta su script de entrada como `__main__`, no como modulo de un
paquete.** Asi que un `from . import entorno` adentro de `aegis_agent/cli.py`
revienta con "attempted relative import with no known parent package" --pero solo
en el ejecutable. Desde el repo, `python -m aegis_agent.cli` funciona perfecto, o
sea que el error es invisible hasta que alguien abre el paquete.

Lo encontro la prueba del `--probar` en `build_windows.py`, que existe justamente
porque un paquete roto se ve igual que uno bueno: los dos pesan lo mismo y los dos
tienen un `.exe` adentro.

El envoltorio hace el import absoluto y deja el paquete intacto.
"""

from aegis_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
