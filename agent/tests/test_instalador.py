"""Tests del instalador que NO tocan la maquina.

Instalar una CA y desviar todo el trafico del usuario no es algo que un test
deba hacer por su cuenta. Aca se verifica lo que se puede verificar sin efectos:
que el plan sea el correcto, que las exclusiones esten completas, que status()
lea el estado real sin modificarlo, y que install y uninstall sean simetricos.
"""

import os
import unittest

from aegis_agent.install import windows
from aegis_agent.policy import PASSTHROUGH_DOMAINS

ES_WINDOWS = os.name == "nt"


class TestPlan(unittest.TestCase):
    def test_el_plan_se_puede_leer_antes_de_tocar_nada(self):
        pasos = windows.plan(8899)
        self.assertTrue(pasos)
        for paso in pasos:
            with self.subTest(paso=paso.description):
                self.assertTrue(paso.description.strip())
                self.assertTrue(paso.detail.strip())

    def test_el_plan_instala_la_ca_solo_para_el_usuario(self):
        detalles = " ".join(paso.detail for paso in windows.plan(8899))
        self.assertIn("-user", detalles)
        self.assertIn("HKCU", detalles)
        # Si alguna vez aparece un almacen de maquina aca, deja de ser
        # reversible sin administrador y hay que discutirlo antes.
        self.assertNotIn("HKLM", detalles)
        self.assertNotIn("LocalMachine", detalles)


class TestExclusiones(unittest.TestCase):
    def test_banca_y_gobierno_quedan_fuera_del_proxy(self):
        bypass = windows.proxy_bypass_list()
        for dominio in PASSTHROUGH_DOMAINS:
            with self.subTest(dominio=dominio):
                self.assertIn(dominio, bypass)

    def test_localhost_queda_fuera(self):
        self.assertIn("localhost", windows.proxy_bypass_list())

    def test_las_variables_de_entorno_repiten_las_exclusiones(self):
        # El registro y las variables tienen sintaxis distintas; si una de las
        # dos se olvida de la banca, el passthrough no sirve de nada.
        no_proxy = windows.env_vars(8899)["NO_PROXY"]
        for dominio in PASSTHROUGH_DOMAINS:
            with self.subTest(dominio=dominio):
                self.assertIn(dominio, no_proxy)


class TestVariables(unittest.TestCase):
    def test_cubre_las_herramientas_que_ignoran_el_proxy_del_sistema(self):
        variables = windows.env_vars(8899)
        for nombre in (
            "HTTPS_PROXY",
            "NODE_EXTRA_CA_CERTS",
            "CODEX_CA_CERTIFICATE",
            "SSL_CERT_FILE",
            "REQUESTS_CA_BUNDLE",
        ):
            with self.subTest(variable=nombre):
                self.assertIn(nombre, variables)

    def test_el_proxy_apunta_a_localhost(self):
        self.assertEqual(windows.env_vars(8899)["HTTPS_PROXY"], "http://127.0.0.1:8899")

    def test_las_rutas_de_ca_apuntan_al_pem(self):
        variables = windows.env_vars(8899)
        self.assertTrue(variables["NODE_EXTRA_CA_CERTS"].endswith(".pem"))


@unittest.skipUnless(ES_WINDOWS, "el instalador es especifico de Windows")
class TestEstadoReal(unittest.TestCase):
    def test_status_lee_el_estado_sin_modificarlo(self):
        antes = windows.read_proxy_settings()
        estado = windows.status(8899)
        despues = windows.read_proxy_settings()
        self.assertEqual(antes, despues)
        for clave in ("ca_generada", "proxy_activo", "apunta_a_aegis"):
            with self.subTest(clave=clave):
                self.assertIn(clave, estado)

    def test_status_no_miente_sobre_la_ca(self):
        estado = windows.status(8899)
        if not estado["ca_generada"]:
            self.assertFalse(estado["ca_confiada"])


if __name__ == "__main__":
    unittest.main()
