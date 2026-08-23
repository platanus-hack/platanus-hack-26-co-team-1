"""La politica deja de ser codigo y pasa a ser un dato: serializar y persistir.

Tres cosas se cubren aca. Que Policy vaya y vuelva de un dict sin perder nada,
que el archivo en disco tolere ausencias y corrupcion sin tumbar al agente
(la politica nunca puede faltar), y que guardar + cargar conserven lo que se
cambio.
"""

import json
import tempfile
import unittest
from pathlib import Path

from aegis_agent import policy_store
from aegis_agent.policy import CustomRule, Policy, decide


class TestIdaYVuelta(unittest.TestCase):
    def test_desde_dict_de_a_dict_reconstruye_una_politica_equivalente(self):
        original = Policy(
            tenant_id="acme",
            approved_ai=frozenset({"claude.ai", "otra-ia.com"}),
            unknown_domain_action="block_content",
            unapproved_ai_action="block_destination",
            model_action="warn",
            model_block_categories=frozenset({"secret"}),
            model_block_labels=frozenset({"nombre de cliente"}),
            block_categories=frozenset({"secret", "internal_data"}),
            warn_categories=frozenset({"pii"}),
            model_labels=("nombre de cliente", "empresa"),
            model_threshold=0.6,
            blind_spot_action="block",
            disabled_rules=frozenset({"email_address"}),
            forbidden_terms=("proyecto orion", "cliente estrella"),
            forbidden_terms_category="secret",
            custom_rules=(
                CustomRule(
                    id="ticket_interno",
                    pattern=r"TKT-\d{6}",
                    category="internal_data",
                    severity="high",
                ),
            ),
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


class TestReglasPersonalizadasTolerantes(unittest.TestCase):
    """Lo que la web mande en custom_rules no puede tumbar al agente.

    La politica la edita gente, no codigo: una entrada a medio guardar, una
    categoria inventada o una severidad que el motor no conoce tienen que
    corregirse o saltarse en silencio. Una severidad desconocida en particular
    haria KeyError en el orden de severidad del engine, asi que se corrige
    aca, antes de que un Finding la toque.
    """

    def test_una_entrada_que_no_es_dict_se_salta(self):
        politica = Policy.desde_dict({"custom_rules": ["esto no es un dict", 42]})
        self.assertEqual(politica.custom_rules, ())

    def test_una_entrada_sin_id_o_sin_patron_se_salta(self):
        politica = Policy.desde_dict(
            {
                "custom_rules": [
                    {"pattern": r"\d+"},
                    {"id": "sin_patron"},
                    {"id": "", "pattern": r"\d+"},
                    {"id": "valida", "pattern": r"TKT-\d+"},
                ]
            }
        )
        self.assertEqual(len(politica.custom_rules), 1)
        self.assertEqual(politica.custom_rules[0].id, "valida")

    def test_categoria_invalida_se_corrige_a_internal_data(self):
        politica = Policy.desde_dict(
            {"custom_rules": [{"id": "x", "pattern": "a", "category": "inventada"}]}
        )
        self.assertEqual(politica.custom_rules[0].category, "internal_data")

    def test_severidad_invalida_se_corrige_a_high(self):
        politica = Policy.desde_dict(
            {"custom_rules": [{"id": "x", "pattern": "a", "severity": "apocaliptica"}]}
        )
        self.assertEqual(politica.custom_rules[0].severity, "high")

    def test_custom_rules_van_y_vuelven_del_json(self):
        original = Policy(
            custom_rules=(CustomRule(id="x", pattern=r"a\d+", category="secret", severity="critical"),)
        )
        recargada = Policy.desde_dict(json.loads(json.dumps(original.a_dict())))
        self.assertEqual(recargada, original)


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
