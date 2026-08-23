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


REVISIONES = ("F", "E9")


def revisar() -> int:
    """Nombres indefinidos, variables muertas e imports sin usar.

    Existe por tres bugs que una auditoria encontro en un solo dia y que la
    suite entera no habia visto NUNCA, porque los tres viven justo en el codigo
    que los tests reemplazan con dobles:

      - `demo/run.py` llamaba a `entorno.mitmdump_en_disco()` sin importar
        `entorno`. `aegis demo` -- la demo del producto -- reventaba con
        NameError, y los e2e no lo tocaban porque levantan su propio arnes.
      - `backend/app.py` anotaba un tipo que no existia.
      - Una variable compilada y nunca usada escondia que `_inspect` ignoraba
        el snapshot de politica del hot-reload.

    Son dos segundos y cazan exactamente esa clase. Solo F y E9: las reglas de
    estilo de ruff chocan a proposito con las convenciones del repo (if/else
    explicito en vez de ternario, un solo return por funcion).

    Y es OPCIONAL. `agent/requirements.txt` esta vacio a proposito -- el agente
    arranca con Python pelado (ver backend/supabase.py) -- asi que exigir ruff
    para poder correr los tests cambiaria esa promesa por una comodidad. Si no
    esta, se dice y se sigue.
    """

    print("\n=== revision estatica ===")
    try:
        completado = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".",
             f"--select={','.join(REVISIONES)}",
             "--exclude=node_modules,dist", "--output-format=concise"],
            cwd=str(RAIZ),
        )
    except (OSError, ValueError):
        completado = None

    if completado is None or completado.returncode > 1:
        print("  ruff no esta instalado; se omite (pip install ruff)")
        resultado = 0
    else:
        resultado = completado.returncode
    return resultado


def main() -> int:
    fallos = correr("agente", RAIZ / "agent")
    backend = RAIZ / "backend" / "tests"
    if backend.exists():
        fallos += correr("backend", RAIZ / "backend")
    fallos += revisar()
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
