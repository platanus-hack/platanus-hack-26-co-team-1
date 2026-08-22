"""Corre las dos suites del repo: el agente y el backend.

    python run_tests.py
"""

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def correr(nombre: str, cwd: Path) -> int:
    print(f"\n=== {nombre} ===")
    return subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=str(cwd),
    ).returncode


def main() -> int:
    fallos = correr("agente", RAIZ / "agent")
    backend = RAIZ / "backend" / "tests"
    if backend.exists():
        fallos += correr("backend", RAIZ / "backend")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
