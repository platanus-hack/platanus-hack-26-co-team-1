"""Tests del instalador que NO tocan la maquina.

Instalar una CA y desviar todo el trafico del usuario no es algo que un test
deba hacer por su cuenta. Aca se verifica lo que se puede verificar sin efectos:
que el plan sea el correcto, que las exclusiones esten completas, que status()
lea el estado real sin modificarlo, y que install y uninstall sean simetricos.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from aegis_agent.install import firewall, windows
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

    def test_las_que_reemplazan_el_almacen_usan_el_bundle(self):
        """La regresion que rompio el equipo entero, no solo a Aegis.

        `SSL_CERT_FILE` y `REQUESTS_CA_BUNDLE` no agregan nuestra CA: reemplazan
        todas. Apuntadas al .pem pelado, el equipo pasa a confiar en UNA sola CA
        y cualquier host que no pase por el proxy --banca, gobierno, o un pypi
        excluido por otra herramienta-- falla con UnknownIssuer. Eso no rompe
        Aegis: rompe cada pip y cada npm de la maquina.
        """

        variables = windows.env_vars(8899)
        for nombre in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
            with self.subTest(variable=nombre):
                self.assertEqual(variables[nombre], str(windows.CA_BUNDLE))
                self.assertNotEqual(variables[nombre], str(windows.CA_PEM))

    def test_las_que_agregan_siguen_con_el_pem_pelado(self):
        """El reverso: pasarles el bundle tampoco seria gratis.

        Node y Codex AGREGAN el archivo a lo que ya confian. Si ademas leyeran
        solo el primer certificado, darles el bundle les haria agregar una raiz
        publica en vez de la nuestra y la interceptacion dejaria de validar.
        Cada variable con la semantica que le toca.
        """

        variables = windows.env_vars(8899)
        for nombre in ("NODE_EXTRA_CA_CERTS", "CODEX_CA_CERTIFICATE"):
            with self.subTest(variable=nombre):
                self.assertEqual(variables[nombre], str(windows.CA_PEM))


class TestBundleDeCAs(unittest.TestCase):
    """El bundle tiene que tener las dos mitades. Siempre, o ninguna."""

    def _entorno_falso(self, carpeta, con_ca_de_aegis=True):
        directorio = Path(carpeta)
        ca_pem = directorio / "mitmproxy-ca-cert.pem"
        if con_ca_de_aegis:
            ca_pem.write_text("-----BEGIN CERTIFICATE-----\\nAEGIS\\n-----END CERTIFICATE-----", encoding="utf-8")
        return directorio, ca_pem, directorio / "mitmproxy-ca-bundle.pem"

    def test_el_bundle_junta_las_publicas_con_la_de_aegis(self):
        with tempfile.TemporaryDirectory() as carpeta:
            directorio, ca_pem, bundle = self._entorno_falso(carpeta)
            with patch.object(windows, "MITM_CA_DIR", directorio), \
                 patch.object(windows, "CA_PEM", ca_pem), \
                 patch.object(windows, "CA_BUNDLE", bundle), \
                 patch.object(windows, "_raices_publicas", return_value=["-----BEGIN CERTIFICATE-----\\nPUBLICA\\n-----END CERTIFICATE-----"]):
                self.assertTrue(windows.escribir_ca_bundle())
            contenido = bundle.read_text(encoding="utf-8")
            self.assertIn("PUBLICA", contenido)
            self.assertIn("AEGIS", contenido)

    def test_sin_raices_publicas_no_escribe_nada(self):
        """Un bundle a medias es peor que ninguno: mejor no tocar el disco."""

        with tempfile.TemporaryDirectory() as carpeta:
            directorio, ca_pem, bundle = self._entorno_falso(carpeta)
            with patch.object(windows, "MITM_CA_DIR", directorio), \
                 patch.object(windows, "CA_PEM", ca_pem), \
                 patch.object(windows, "CA_BUNDLE", bundle), \
                 patch.object(windows, "_raices_publicas", return_value=[]):
                self.assertFalse(windows.escribir_ca_bundle())
            self.assertFalse(bundle.exists())

    def test_sin_la_ca_de_aegis_tampoco_escribe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            directorio, ca_pem, bundle = self._entorno_falso(carpeta, con_ca_de_aegis=False)
            with patch.object(windows, "MITM_CA_DIR", directorio), \
                 patch.object(windows, "CA_PEM", ca_pem), \
                 patch.object(windows, "CA_BUNDLE", bundle), \
                 patch.object(windows, "_raices_publicas", return_value=["-----BEGIN CERTIFICATE-----\\nPUBLICA\\n-----END CERTIFICATE-----"]):
                self.assertFalse(windows.escribir_ca_bundle())
            self.assertFalse(bundle.exists())

    def test_las_raices_publicas_no_vienen_vacias(self):
        """Si esto falla, el instalador no va a poder escribir ningun bundle."""

        self.assertTrue(windows._raices_publicas())

    def test_si_el_bundle_falla_no_se_tocan_las_variables(self):
        """El invariante: antes sin interceptar los CLIs que sin HTTPS."""

        with patch.object(windows, "ensure_ca", return_value=True), \
             patch.object(windows, "trust_ca", return_value=True), \
             patch.object(windows, "escribir_ca_bundle", return_value=False), \
             patch.object(windows, "registrar_arranque", return_value=True), \
             patch.object(windows, "registrar_en_programas", return_value=True), \
             patch.object(windows, "set_env_vars") as poner:
            hechos = windows.install(8899)
        poner.assert_not_called()
        self.assertTrue(any("NO se escribio el bundle" in hecho for hecho in hechos))

    def test_desinstalar_saca_el_bundle_que_instalar_dejo(self):
        with patch.object(windows, "write_proxy_settings"), \
             patch.object(windows, "untrust_ca", return_value=False), \
             patch.object(windows, "clear_env_vars"), \
             patch.object(windows, "quitar_arranque", return_value=False), \
             patch.object(windows, "quitar_de_programas", return_value=False), \
             patch.object(windows, "borrar_ca_bundle", return_value=True) as borrar, \
             patch.object(firewall, "reglas_puestas", return_value=[]):
            hechos = windows.uninstall()
        borrar.assert_called_once()
        self.assertTrue(any("Bundle de CAs eliminado" in hecho for hecho in hechos))


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


class TestSeEncuentraParaDesinstalar(unittest.TestCase):
    """Donde la gente busca para desinstalar algo no es una terminal.

    Sin la entrada en "Agregar o quitar programas", la unica forma de sacar
    Aegis era acordarse de un comando -- y quien quiere desinstalar algo suele
    ser justo quien no quiere aprender su CLI. En un producto que toca el proxy
    del sistema eso termina mal: el que no encuentra como sacarlo borra el .exe,
    y el proxy queda apuntando a un puerto muerto. Sin internet y sin nada que
    apretar.
    """

    def test_instalar_lo_deja_en_la_lista_de_programas(self):
        from aegis_agent.install import windows

        with patch.object(windows, "ensure_ca", return_value=True), \
             patch.object(windows, "trust_ca", return_value=True), \
             patch.object(windows, "escribir_ca_bundle", return_value=True), \
             patch.object(windows, "set_env_vars"), \
             patch.object(windows, "registrar_arranque", return_value=True), \
             patch.object(windows, "registrar_en_programas", return_value=True) as registrar:
            hechos = windows.install(8899)
        registrar.assert_called_once()
        self.assertTrue(any("quitar programas" in h for h in hechos))

    def test_desinstalar_lo_saca_de_la_lista(self):
        from aegis_agent.install import windows

        with patch.object(windows, "write_proxy_settings"), \
             patch.object(windows, "untrust_ca", return_value=False), \
             patch.object(windows, "clear_env_vars"), \
             patch.object(windows, "quitar_arranque", return_value=True), \
             patch.object(windows, "quitar_de_programas", return_value=True) as quitar, \
             patch.object(firewall, "reglas_puestas", return_value=[]):
            hechos = windows.uninstall()
        quitar.assert_called_once()
        self.assertTrue(any("quitar programas" in h for h in hechos))

    def test_el_comando_de_desinstalacion_es_el_que_se_puede_correr(self):
        """Si el UninstallString estuviera mal, el boton de Windows no haria nada."""

        from aegis_agent import entorno
        from aegis_agent.install import windows

        guardados = {}
        winreg = MagicMock()
        winreg.CreateKey.return_value.__enter__ = lambda s: "clave"
        winreg.CreateKey.return_value.__exit__ = lambda *a: None
        winreg.SetValueEx.side_effect = lambda c, n, r, t, v: guardados.__setitem__(n, v)

        with patch.object(windows, "_registry", return_value=winreg):
            self.assertTrue(windows.registrar_en_programas())

        self.assertIn("desinstalar", guardados["UninstallString"])
        self.assertTrue(
            any(p in guardados["UninstallString"] for p in entorno.ejecutable_del_agente())
        )
