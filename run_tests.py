"""Corre las dos suites del repo: el agente y el backend.

    python run_tests.py
"""

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def correr(nombre: str, cwd: Path) -> int:
    print(f"\n=== {nombre} ===")
    # La suite no puede tocar nada de produccion, y hay dos caminos por los que
    # llegaba sola.
    #
    # 1. Las credenciales de Supabase viven en ~/.aegis/secretos.env, que es del
    #    HOME de quien corre esto: sin apagarlo, la suite de cualquiera que
    #    tenga la base configurada escribe veredictos de prueba en la tabla que
    #    usa la demo.
    # 2. El instalador deja AEGIS_EVENTS_URL en el entorno de USUARIO apuntando
    #    al panel desplegado. Cada proxy que levantan los e2e la heredaba y
    #    subia sus eventos de mentira al panel real. Mientras el panel guardaba
    #    en memoria no se notaba; con la base conectada, quedan.
    #
    # Va aca ademas de en tests/aislamiento.py a proposito: el helper solo
    # protege a los tests que se acuerdan de usarlo.
    entorno = {
        **os.environ,
        "AEGIS_SUPABASE_DISABLED": "1",
        "AEGIS_EVENTS_URL": "",
    }
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=str(cwd),
        env=entorno,
    ).returncode


def main() -> int:
    fallos = correr("agente", RAIZ / "agent")
    backend = RAIZ / "backend" / "tests"
    if backend.exists():
        fallos += correr("backend", RAIZ / "backend")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
