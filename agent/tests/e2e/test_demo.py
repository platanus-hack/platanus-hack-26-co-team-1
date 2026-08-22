"""Demo end-to-end: un navegador real intentando filtrar datos a una IA.

Levanta el proxy con el addon de Aegis, abre Chromium a traves de el y recorre
los cuatro casos que definen el producto:

  1. IA aprobada + texto limpio  -> pasa, porque el objetivo es que la gente use
                                    la herramienta que la empresa si aprobo
  2. IA aprobada + credenciales  -> se corta el dato, no la herramienta
  3. IA no aprobada              -> se corta el destino (shadow AI)
  4. Dominio desconocido con forma de API de IA -> se corta igual

Ejecutar:  python -m tests.e2e.test_demo   (o via unittest)
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
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent.parent

PROXY_PORT = 8899
PROXY_HOST = "127.0.0.1"
STARTUP_TIMEOUT = 40

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"

CLEAN_PROMPT = (
    "Ayudame a escribir el copy de la campana de septiembre para redes sociales."
)

SENSITIVE_FILE = f"""# credenciales de produccion
AWS_ACCESS_KEY_ID={AWS_KEY}
DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod
"""


def _mitmdump_path() -> str:
    """mitmdump se instala como ejecutable, no como modulo invocable."""

    scripts = sysconfig.get_path("scripts", scheme="nt_user" if os.name == "nt" else "posix_user")
    candidate = Path(scripts) / ("mitmdump.exe" if os.name == "nt" else "mitmdump")
    return str(candidate) if candidate.exists() else "mitmdump"


def _port_open(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex((PROXY_HOST, port)) == 0


class AegisDemo(unittest.TestCase):
    proxy: subprocess.Popen
    queue: Path
    workdir: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls.workdir = tempfile.TemporaryDirectory()
        cls.queue = Path(cls.workdir.name) / "eventos.jsonl"

        env = dict(os.environ)
        env["AEGIS_QUEUE"] = str(cls.queue)
        env["PYTHONPATH"] = str(AGENT_ROOT)

        cls.proxy = subprocess.Popen(
            [
                _mitmdump_path(),
                "--listen-port",
                str(PROXY_PORT),
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
        while time.time() < deadline and not _port_open(PROXY_PORT):
            time.sleep(0.2)
        if not _port_open(PROXY_PORT):
            output = cls.proxy.stdout.read().decode("utf-8", "replace") if cls.proxy.stdout else ""
            raise RuntimeError(f"el proxy no levanto en {STARTUP_TIMEOUT}s:\n{output}")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            proxy={"server": f"http://{PROXY_HOST}:{PROXY_PORT}"}
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.proxy.terminate()
        cls.proxy.wait(timeout=10)
        cls.workdir.cleanup()

    def _page(self):
        context = self.browser.new_context(ignore_https_errors=True)
        self.addCleanup(context.close)
        return context.new_page()

    def _upload(self, page, host: str, contents: str, prompt: str = CLEAN_PROMPT):
        path = Path(self.workdir.name) / "adjunto.env"
        path.write_text(contents, encoding="utf-8")
        page.goto(f"https://{host}/", wait_until="domcontentloaded")
        page.fill("#prompt", prompt)
        page.set_input_files("#archivo", str(path))
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")

    def _events(self) -> list[dict]:
        if not self.queue.exists():
            return []
        lines = self.queue.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def test_1_ia_aprobada_con_texto_limpio_pasa(self):
        page = self._page()
        page.goto("https://claude.ai/", wait_until="domcontentloaded")
        page.fill("#prompt", CLEAN_PROMPT)
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")
        self.assertIn("Respuesta del modelo", page.content())

    def test_2_ia_aprobada_con_archivo_sensible_se_bloquea(self):
        page = self._page()
        self._upload(page, "claude.ai", SENSITIVE_FILE)
        content = page.content()
        self.assertIn("no debe salir", content)
        self.assertIn("aws_access_key_id", content)
        self.assertNotIn(AWS_KEY, content)
        self.assertIn("credenciales de AWS", content)

    def test_3_ia_no_aprobada_se_bloquea_el_destino(self):
        page = self._page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        content = page.content()
        self.assertIn("no esta aprobado", content)
        self.assertIn("claude.ai", content)

    def test_4_dominio_desconocido_con_forma_de_ia_se_bloquea(self):
        page = self._page()
        self._upload(page, "asistente-magico.co", SENSITIVE_FILE)
        self.assertIn("no debe salir", page.content())

    def test_5_sitio_interno_no_ia_no_se_interrumpe(self):
        page = self._page()
        self._upload(page, "intranet.acme.co", SENSITIVE_FILE)
        self.assertIn("Respuesta del modelo", page.content())

    def test_6_los_eventos_registrados_no_llevan_el_secreto(self):
        page = self._page()
        self._upload(page, "claude.ai", SENSITIVE_FILE)
        events = self._events()
        self.assertTrue(events, "no se registro ningun evento")
        raw = json.dumps(events, ensure_ascii=False)
        self.assertNotIn(AWS_KEY, raw)
        self.assertNotIn("s3cr3t", raw)
        blocked = [e for e in events if e["action"] == "blocked"]
        self.assertTrue(blocked)
        self.assertTrue(any(e["detection"] for e in blocked))


if __name__ == "__main__":
    unittest.main(verbosity=2)
