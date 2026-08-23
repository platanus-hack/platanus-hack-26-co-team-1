"""Lo que ve una app que no es el navegador.

Un CLI de IA, un IDE o una app de escritorio no leen el proxy del registro:
leen variables de entorno y un archivo de CA. Ese es todo el contrato, y hasta
aca nadie lo habia probado. Si este test se cae, Claude Code y Codex quedan
fuera de Aegis sin que nada mas se entere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from .harness import ProxyHarness

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aegis_agent.install.windows import CA_PEM, env_vars  # noqa: E402

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"

# El cliente sabe exactamente lo que sabe un CLI recien instalado: nada, salvo
# las variables que le dejo el instalador. Sin proxy del sistema, sin config.
_CLIENTE = """
import json, sys, urllib.error, urllib.request

peticion = urllib.request.Request(
    sys.argv[1],
    data=json.dumps(
        {"model": "claude-opus-4", "messages": [{"role": "user", "content": sys.argv[2]}]}
    ).encode(),
    headers={"Content-Type": "application/json", "Accept": "application/json"},
)
try:
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        print(respuesta.status)
        print(respuesta.read().decode("utf-8", "replace"))
except urllib.error.HTTPError as error:
    print(error.code)
    print(error.read().decode("utf-8", "replace"))
"""


class EscritorioE2E(ProxyHarness, unittest.TestCase):
    # Equilibrado y contra una IA aprobada: asi lo que decide es el contenido y
    # no el destino, que es lo que este test quiere aislar.
    MODO = "equilibrado"

    def _entorno(self) -> dict[str, str]:
        # Se arma desde cero en vez de copiar os.environ: heredar el entorno del
        # test escondería que el instalador se olvido de alguna variable.
        esenciales = ("SystemRoot", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT")
        entorno = {
            clave: os.environ[clave] for clave in esenciales if clave in os.environ
        }
        entorno.update(env_vars(self.port))
        return entorno

    def _cliente(self, texto: str, url: str = "https://claude.ai/api/chat"):
        proceso = subprocess.run(
            [sys.executable, "-c", _CLIENTE, url, texto],
            env=self._entorno(),
            capture_output=True,
            text=True,
            timeout=90,
        )
        salida = proceso.stdout.strip().split("\n", 1)
        if len(salida) != 2:
            self.fail(
                f"el cliente no llego a hablar con el proxy.\n"
                f"stdout: {proceso.stdout}\nstderr: {proceso.stderr}"
            )
        return int(salida[0]), salida[1]

    def setUp(self) -> None:
        if not CA_PEM.exists():
            self.skipTest(f"falta la CA en {CA_PEM}")

    def test_un_cli_solo_con_variables_de_entorno_queda_cubierto(self):
        codigo, cuerpo = self._cliente(f"mi llave es {AWS_KEY}")
        self.assertEqual(codigo, 403)
        self.assertIn("aegis_blocked", cuerpo)

    def test_a_una_app_se_le_responde_json_y_no_html(self):
        """Contestarle HTML a un cliente de API lo deja girando para siempre.

        Recibe algo que no sabe interpretar y no muestra ningun error, asi que la
        persona no entiende que paso: exactamente lo que Aegis existe para evitar.
        """

        _, cuerpo = self._cliente(f"mi llave es {AWS_KEY}")
        self.assertNotIn("<!doctype", cuerpo.lower())
        error = json.loads(cuerpo)["error"]
        self.assertEqual(error["type"], "aegis_blocked")
        self.assertTrue(error["message"].strip())

    def test_el_trabajo_normal_sigue_pasando(self):
        codigo, _ = self._cliente("ayudame a escribir un README corto")
        self.assertEqual(codigo, 200)


if __name__ == "__main__":
    unittest.main()
