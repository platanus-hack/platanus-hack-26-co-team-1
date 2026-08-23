"""Arnes compartido: proxy real, navegador real, upstream simulado.

Cada clase de test levanta su propio proxy en un puerto libre. Reusar un puerto
fijo entre clases deja sockets en TIME_WAIT y la suite falla de forma
intermitente, que es la peor clase de test que existe.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from aegis_agent import entorno
from tests.aislamiento import variables_aisladas

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent.parent

STARTUP_TIMEOUT = 40
HOST = "127.0.0.1"


def mitmdump_path() -> str:
    """El ejecutable de mitmproxy, para los tests que levantan un proxy de verdad.

    La busqueda vive en aegis_agent.entorno: estaba duplicada aca y en demo/run.py,
    y el instalador de produccion importaba ESTA copia --un modulo de tests.
    """

    return entorno.mitmdump_en_disco() or "mitmdump"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((HOST, port)) == 0


class ProxyHarness:
    """Mixin para tests que necesitan el proxy y un navegador.

    MODO decide que hace el agente con una IA no aprobada. Se fija por clase y no
    por variable de entorno global para que las dos politicas se puedan probar en
    la misma corrida.
    """

    MODO = "estricto"

    @classmethod
    def setUpClass(cls) -> None:
        cls.workdir = tempfile.TemporaryDirectory()
        cls.queue = Path(cls.workdir.name) / "eventos.jsonl"
        cls.port = _free_port()

        env = dict(os.environ)
        env["AEGIS_QUEUE"] = str(cls.queue)
        env["PYTHONPATH"] = str(AGENT_ROOT)
        # Los e2e no dependen del backend: lo que se prueba aca es el agente.
        env["AEGIS_BACKEND_DISABLED"] = "1"
        env["AEGIS_MODO"] = cls.MODO
        env["AEGIS_DOMAIN_CACHE"] = str(Path(cls.workdir.name) / "dominios.json")
        # Sin esto el proxy hijo lee ~/.aegis/politica.json, o sea lo que haya
        # dejado cualquier otra corrida en la maquina, y el MODO de arriba se
        # vuelve decorativo.
        env.update(variables_aisladas(cls.workdir.name))

        cls.proxy = subprocess.Popen(
            [
                mitmdump_path(),
                # A loopback y no a todas las interfaces: un proxy que descifra
                # TLS abierto a la red local es un regalo para cualquiera que
                # este en el mismo wifi.
                "--listen-host",
                "127.0.0.1",
                "--listen-port",
                str(cls.port),
                "--quiet",
                # Sin esto mitmproxy intenta conectar al servidor real antes de
                # que el addon decida, y los dominios de la demo no existen.
                "--set",
                "connection_strategy=lazy",
                "--set",
                "upstream_cert=false",
                "-s",
                str(AGENT_ROOT / "aegis_mitm.py"),
                "-s",
                str(HERE / "mock_upstream.py"),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(AGENT_ROOT),
        )

        deadline = time.time() + STARTUP_TIMEOUT
        while time.time() < deadline and not _port_open(cls.port):
            time.sleep(0.2)
        if not _port_open(cls.port):
            salida = cls.proxy.stdout.read().decode("utf-8", "replace") if cls.proxy.stdout else ""
            raise RuntimeError(f"el proxy no levanto en {STARTUP_TIMEOUT}s:\n{salida}")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            proxy={"server": f"http://{HOST}:{cls.port}"}
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.proxy.terminate()
        cls.proxy.wait(timeout=10)
        cls.workdir.cleanup()

    def page(self):
        context = self.browser.new_context(ignore_https_errors=True)
        self.addCleanup(context.close)
        return context.new_page()

    def upload(self, page, host: str, contenido: str, prompt: str = "Revisa esto por favor"):
        ruta = Path(self.workdir.name) / "adjunto.env"
        ruta.write_text(contenido, encoding="utf-8")
        page.goto(f"https://{host}/", wait_until="domcontentloaded")
        page.fill("#prompt", prompt)
        page.set_input_files("#archivo", str(ruta))
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")

    def events(self) -> list[dict]:
        if not self.queue.exists():
            return []
        return [
            json.loads(line)
            for line in self.queue.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
