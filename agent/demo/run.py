"""Demo manual: levanta Aegis y un navegador para probarlo a mano.

Es el mismo proxy y el mismo motor que corren en los tests; lo unico distinto es
que el navegador queda abierto para que la persona intente filtrar el archivo
ella misma. No hace falta instalar la CA porque el navegador de la demo se lanza
confiando en el certificado del proxy.

    python -m demo.run
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

AGENT_ROOT = Path(__file__).resolve().parent.parent
MOCK = AGENT_ROOT / "tests" / "e2e" / "mock_upstream.py"

PROXY_PORT = 8899
PROXY_HOST = "127.0.0.1"

SENSITIVE_FILE = """# credenciales de produccion - NO COMPARTIR
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod
STRIPE_KEY=sk_live_4eC39HqLyjWDarjtT1zdp7dc
"""


def _mitmdump_path() -> str:
    """Delegado en aegis_agent.entorno: estaba duplicado aca y en el harness."""

    return entorno.mitmdump_en_disco() or "mitmdump"


def _wait_for_port(port: int, timeout: float = 40) -> bool:
    deadline = time.time() + timeout
    ready = False
    while time.time() < deadline and not ready:
        with socket.socket() as probe:
            probe.settimeout(0.4)
            ready = probe.connect_ex((PROXY_HOST, port)) == 0
        if not ready:
            time.sleep(0.2)
    return ready


def main() -> int:
    workdir = tempfile.mkdtemp(prefix="aegis-demo-")
    queue = Path(workdir) / "eventos.jsonl"
    sample = Path(workdir) / "credenciales-produccion.env"
    sample.write_text(SENSITIVE_FILE, encoding="utf-8")

    env = dict(os.environ)
    env["AEGIS_QUEUE"] = str(queue)
    env["PYTHONPATH"] = str(AGENT_ROOT)

    proxy = subprocess.Popen(
        [
            _mitmdump_path(),
            # A loopback y no a todas las interfaces: un proxy que descifra
            # TLS abierto a la red local es un regalo para cualquiera que
            # este en el mismo wifi.
            "--listen-host",
            "127.0.0.1",
            "--listen-port",
            str(PROXY_PORT),
            "--quiet",
            "--set",
            "connection_strategy=lazy",
            "--set",
            "upstream_cert=false",
            "-s",
            str(AGENT_ROOT / "aegis_mitm.py"),
            "-s",
            str(MOCK),
        ],
        env=env,
        cwd=str(AGENT_ROOT),
    )

    if not _wait_for_port(PROXY_PORT):
        proxy.terminate()
        print("El proxy no levanto.", file=sys.stderr)
        return 1

    print("Aegis corriendo en %s:%s" % (PROXY_HOST, PROXY_PORT))
    print("Archivo de prueba: %s" % sample)
    print("Eventos: %s" % queue)
    print("\nProba en el navegador que se acaba de abrir:")
    print("  1. https://claude.ai/            IA aprobada: escribi y enviá, pasa")
    print("  2. https://claude.ai/            ahora adjunta el archivo de prueba")
    print("  3. https://novaai.local/         IA no aprobada: se corta el destino")
    print("  4. https://asistente-magico.co/  dominio desconocido con forma de IA")
    print("  5. https://intranet.acme.co/     sitio interno: el archivo pasa\n")
    print("Cerra el navegador para terminar.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            proxy={"server": f"http://{PROXY_HOST}:{PROXY_PORT}"},
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto("https://claude.ai/", wait_until="domcontentloaded")
        while len(context.pages) > 0:
            time.sleep(0.5)

    proxy.terminate()
    proxy.wait(timeout=10)

    if queue.exists():
        print("\nEventos registrados:")
        print(queue.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
