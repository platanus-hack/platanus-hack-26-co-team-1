"""La politica deja de ser codigo y pasa a ser un dato: serializar y persistir.

Tres cosas se cubren aca. Que Policy vaya y vuelva de un dict sin perder nada,
que el archivo en disco tolere ausencias y corrupcion sin tumbar al agente
(la politica nunca puede faltar), y que guardar + cargar conserven lo que se
cambio.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aegis_agent import policy_store
from aegis_agent.policy import Policy, decide


class TestIdaYVuelta(unittest.TestCase):
    def test_desde_dict_de_a_dict_reconstruye_una_politica_equivalente(self):
        original = Policy(
            tenant_id="acme",
            approved_ai=frozenset({"claude.ai", "otra-ia.com"}),
            unknown_domain_action="block_content",
            unapproved_ai_action="block_destination",
            model_action="warn",
            model_block_categories=frozenset({"secret"}),
            model_warn_categories=frozenset({"pii", "internal_data"}),
            model_block_labels=frozenset({"nombre de cliente"}),
            block_categories=frozenset({"secret", "internal_data"}),
            warn_categories=frozenset({"pii"}),
            model_labels=("nombre de cliente", "empresa"),
            model_threshold=0.6,
            blind_spot_action="block",
        )

        reconstruida = Policy.desde_dict(original.a_dict())

        self.assertEqual(reconstruida, original)

    def test_a_dict_serializa_los_frozenset_como_listas_ordenadas(self):
        original = Policy(approved_ai=frozenset({"b.com", "a.com", "c.com"}))
        datos = original.a_dict()
        self.assertEqual(datos["approved_ai"], ["a.com", "b.com", "c.com"])
        self.assertIsInstance(datos["approved_ai"], list)

    def test_a_dict_es_json_serializable(self):
        # Si alguno de los campos no fuera un tipo JSON (un frozenset suelto,
        # por ejemplo), esto lanzaria TypeError.
        json.dumps(Policy().a_dict())


class TestClavesAusentesYDesconocidas(unittest.TestCase):
    def test_claves_ausentes_caen_al_default(self):
        reconstruida = Policy.desde_dict({"tenant_id": "otra-empresa"})
        default = Policy()

        self.assertEqual(reconstruida.tenant_id, "otra-empresa")
        self.assertEqual(reconstruida.model_action, default.model_action)
        self.assertEqual(reconstruida.model_labels, default.model_labels)
        self.assertEqual(reconstruida.model_threshold, default.model_threshold)
        self.assertEqual(reconstruida.blind_spot_action, default.blind_spot_action)

    def test_una_clave_desconocida_no_revienta(self):
        datos = Policy().a_dict()
        datos["campo_del_futuro_que_este_agente_no_conoce"] = "algo"

        reconstruida = Policy.desde_dict(datos)

        self.assertEqual(reconstruida, Policy())

    def test_diccionario_vacio_da_los_defaults(self):
        self.assertEqual(Policy.desde_dict({}), Policy())


class TestAlmacen(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.ruta = Path(self.workdir.name) / "politica.json"

    def test_cargar_sin_archivo_devuelve_los_defaults(self):
        self.assertEqual(policy_store.cargar(self.ruta), Policy())

    def test_cargar_con_json_corrupto_devuelve_los_defaults_y_no_lanza(self):
        self.ruta.write_text("{esto no es json valido", encoding="utf-8")
        self.assertEqual(policy_store.cargar(self.ruta), Policy())

    def test_cargar_con_archivo_vacio_devuelve_los_defaults(self):
        self.ruta.write_text("", encoding="utf-8")
        self.assertEqual(policy_store.cargar(self.ruta), Policy())

    def test_guardar_y_cargar_conservan_lo_que_se_cambio(self):
        politica = Policy(tenant_id="empresa-x", model_threshold=0.7, blind_spot_action="block")
        policy_store.guardar(politica, self.ruta)

        recargada = policy_store.cargar(self.ruta)

        self.assertEqual(recargada, politica)

    def test_guardar_crea_el_directorio_si_hace_falta(self):
        ruta_anidada = Path(self.workdir.name) / "sub" / "dir" / "politica.json"
        policy_store.guardar(Policy(tenant_id="anidada"), ruta_anidada)

        self.assertTrue(ruta_anidada.exists())
        self.assertEqual(policy_store.cargar(ruta_anidada).tenant_id, "anidada")

    def test_guardar_escribe_json_legible_e_indentado(self):
        policy_store.guardar(Policy(), self.ruta)
        contenido = self.ruta.read_text(encoding="utf-8")
        # Si no fuera indentado, todo el JSON entraria en una sola linea.
        self.assertIn("\n", contenido)
        json.loads(contenido)  # no lanza


class TestElModoDelEntorno(unittest.TestCase):
    """AEGIS_MODO tiene que seguir existiendo despues de la primera politica.

    La politica guardada es de la empresa y llega del backend; AEGIS_MODO la
    pone quien instala el agente en el equipo. Cuando el archivo mandaba solo,
    el interruptor documentado en OPERACION.md se moria en silencio apenas el
    agente cacheaba una politica por primera vez.
    """

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.ruta = Path(self.workdir.name) / "politica.json"
        policy_store.guardar(Policy(unapproved_ai_action="inspect"), self.ruta)

    def test_estricto_le_gana_al_archivo_que_dice_equilibrado(self):
        with patch.dict(os.environ, {"AEGIS_MODO": "estricto"}):
            self.assertEqual(
                policy_store.cargar(self.ruta).unapproved_ai_action, "block_destination"
            )

    def test_equilibrado_le_gana_al_archivo_que_dice_estricto(self):
        policy_store.guardar(Policy(unapproved_ai_action="block_destination"), self.ruta)
        with patch.dict(os.environ, {"AEGIS_MODO": "equilibrado"}):
            self.assertEqual(policy_store.cargar(self.ruta).unapproved_ai_action, "inspect")

    def test_sin_la_variable_manda_el_archivo(self):
        policy_store.guardar(Policy(unapproved_ai_action="block_destination"), self.ruta)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AEGIS_MODO", None)
            self.assertEqual(
                policy_store.cargar(self.ruta).unapproved_ai_action, "block_destination"
            )

    def test_un_modo_que_no_existe_no_pisa_al_archivo(self):
        # Un typo en la variable no puede aflojar ni endurecer la politica de la
        # empresa por accidente: si no es un modo, no es una decision.
        policy_store.guardar(Policy(unapproved_ai_action="block_destination"), self.ruta)
        with patch.dict(os.environ, {"AEGIS_MODO": "estrikto"}):
            self.assertEqual(
                policy_store.cargar(self.ruta).unapproved_ai_action, "block_destination"
            )

    def test_la_ruta_sale_de_aegis_politica(self):
        with patch.dict(os.environ, {"AEGIS_POLITICA": str(self.ruta)}):
            os.environ.pop("AEGIS_MODO", None)
            self.assertEqual(policy_store.cargar().unapproved_ai_action, "inspect")


class TestImportarNoTieneEfectos(unittest.TestCase):
    """Importar el addon no puede levantar un agente.

    Cuando `addons = [Aegis()]` vivia al final de addon.py, cualquier import del
    modulo leia la politica del HOME, se la pedia al backend por la red y
    arrancaba el sensor de conexiones. La suite terminaba escribiendole
    ~/.aegis/politica.json a quien la corriera, y los e2e despues obedecian ese
    archivo en vez del AEGIS_MODO que ellos mismos ponian.
    """

    def test_importar_el_addon_no_escribe_la_politica_del_usuario(self):
        with tempfile.TemporaryDirectory() as workdir:
            hogar = Path(workdir) / "hogar"
            hogar.mkdir()
            entorno = dict(os.environ)
            entorno["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            entorno.pop("AEGIS_POLITICA", None)
            # HOME y USERPROFILE: Path.home() mira uno u otro segun el sistema.
            entorno["HOME"] = str(hogar)
            entorno["USERPROFILE"] = str(hogar)

            subprocess.run(
                [sys.executable, "-c", "import aegis_agent.proxy.addon"],
                env=entorno,
                check=True,
                capture_output=True,
                timeout=60,
            )

            self.assertFalse(
                (hogar / ".aegis").exists(),
                "importar el addon le escribio la politica al usuario",
            )

    def test_el_modulo_no_expone_una_lista_de_addons_ya_construida(self):
        # El punto de entrada de mitmproxy es aegis_mitm.py y es el unico lugar
        # donde se instancia. Si esto vuelve, vuelve el efecto de import.
        from aegis_agent.proxy import addon

        self.assertFalse(hasattr(addon, "addons"))

class TestDestinoDesconocido(unittest.TestCase):
    """decide() para lo que sale hacia un dominio non_ai, segun unknown_domain_action.

    unknown_domain_action existia en la politica y se serializaba, pero decide()
    nunca la leia: un dominio sin clasificar siempre daba "allow" sin importar
    lo que hubiera en el body. Estos tests conectan esa perilla.
    """

    def test_sin_hallazgos_siempre_deja_pasar_sin_importar_el_modo(self):
        for modo in ("warn", "block_content", "allow"):
            with self.subTest(modo=modo):
                politica = Policy(unknown_domain_action=modo)
                self.assertEqual(decide("non_ai", set(), politica), "allow")

    def test_modo_warn_no_bloquea_ni_siquiera_un_secreto(self):
        # "warn" es el default: la lista negra crece por la visibilidad, no
        # porque el primer envio se corte.
        politica = Policy(unknown_domain_action="warn")
        self.assertEqual(decide("non_ai", {"secret"}, politica), "warn")

    def test_modo_block_content_corta_un_secreto(self):
        politica = Policy(unknown_domain_action="block_content")
        self.assertEqual(decide("non_ai", {"secret"}, politica), "block_content")

    def test_modo_block_content_solo_avisa_de_un_dato_personal(self):
        politica = Policy(unknown_domain_action="block_content")
        self.assertEqual(decide("non_ai", {"pii"}, politica), "warn")

    def test_modo_allow_es_la_salida_de_emergencia_aunque_haya_un_secreto(self):
        politica = Policy(unknown_domain_action="allow")
        self.assertEqual(decide("non_ai", {"secret"}, politica), "allow")


if __name__ == "__main__":
    unittest.main()
