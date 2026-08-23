"""Los cuatro campos que la pantalla de Politicas mostraba y la politica no tenia.

La pantalla dejaba prohibir dominios, apagar una regla suelta y hacer
excepciones por persona o por area. Nada de eso existia del lado del agente: el
formulario se llenaba, se guardaba, y no cambiaba una sola decision.

Declararlos sin que decidan nada habria sido peor que no tenerlos, porque el
panel prometeria algo que no ocurre. Esto prueba que deciden.

El orden de precedencia es lo que mas importa y esta al final:

    dominio prohibido  >  excepcion por persona  >  excepcion por area  >  regla

Un dominio prohibido no lo afloja nadie: es la unica regla de la politica que
expresa una prohibicion y no una gradacion. Si una excepcion pudiera levantarlo,
prohibir no significaria nada.
"""

from __future__ import annotations

import unittest

from aegis_agent.detect.types import Finding
from aegis_agent.policy import Policy, decidir_sobre, modo_de_la_persona


def hallazgo(rule_id="aws_access_key_id", category="secret", severity="critical"):
    return Finding(
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence=1.0,
        evidence="AKIA****",
        start=0,
        end=8,
    )


class TestDominiosProhibidos(unittest.TestCase):
    def test_un_dominio_prohibido_corta_aunque_no_haya_hallazgos(self):
        politica = Policy(blocked_domains=frozenset({"deepseek.com"}))
        self.assertEqual(
            decidir_sobre("ai_unapproved", [], politica, host="deepseek.com"),
            "block_content",
        )

    def test_un_subdominio_tambien(self):
        # Nadie va a enumerar los subdominios de un servicio que justamente no
        # quiere usar.
        politica = Policy(blocked_domains=frozenset({"deepseek.com"}))
        self.assertEqual(
            decidir_sobre("ai_unapproved", [], politica, host="chat.deepseek.com"),
            "block_content",
        )

    def test_un_dominio_que_solo_termina_parecido_no_cuenta(self):
        # "nodeepseek.com" no es un subdominio de "deepseek.com".
        politica = Policy(blocked_domains=frozenset({"deepseek.com"}))
        self.assertEqual(
            decidir_sobre("ai_approved", [], politica, host="nodeepseek.com"), "allow"
        )

    def test_sin_lista_no_cambia_nada(self):
        self.assertEqual(decidir_sobre("ai_approved", [], Policy(), host="claude.ai"), "allow")

    def test_la_lista_blanca_no_sirve_para_prohibir(self):
        """Por que blocked_domains existe en vez de ser el complemento de approved_ai.

        `approved_ai` responde "esto esta aprobado". Una empresa que quiere
        prohibir deepseek.com no tiene como decirlo sacandolo de una lista donde
        nunca estuvo.
        """

        sin_prohibir = Policy(approved_ai=frozenset({"claude.ai"}))
        self.assertNotEqual(
            decidir_sobre("ai_unapproved", [], sin_prohibir, host="deepseek.com"),
            "block_content",
        )


class TestAccionPorRegla(unittest.TestCase):
    def test_apagar_una_regla_no_apaga_su_categoria(self):
        """El caso que lo motivo: callar `email_address` sin bajar todo `pii`.

        Antes la eleccion era todo o nada: o la categoria entera avisaba, o la
        categoria entera se apagaba.
        """

        politica = Policy(rule_actions={"email_address": "off"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo("email_address", "pii", "medium")], politica),
            "allow",
        )
        # Otra regla de la misma categoria sigue decidiendo como siempre.
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo("latam_national_id", "pii", "medium")], politica),
            "warn",
        )

    def test_una_regla_puede_subir_a_bloqueo(self):
        politica = Policy(rule_actions={"email_address": "block"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo("email_address", "pii", "medium")], politica),
            "block_content",
        )

    def test_una_regla_puede_bajar_a_aviso(self):
        politica = Policy(rule_actions={"aws_access_key_id": "warn"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo()], politica), "warn"
        )

    def test_un_valor_desconocido_se_ignora(self):
        # Una politica escrita por un panel mas nuevo no puede romper al agente.
        politica = Policy(rule_actions={"aws_access_key_id": "quizas"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo()], politica), "block_content"
        )


class TestExcepcionesPorPersonaYArea(unittest.TestCase):
    def test_una_persona_nombrada_pasa_a_observacion(self):
        politica = Policy(user_actions={"u_dev": "observar"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo()], politica, usuario="u_dev"), "warn"
        )

    def test_un_area_entera_tambien(self):
        politica = Policy(area_actions={"ingenieria": "observar"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo()], politica, area="ingenieria"), "warn"
        )

    def test_la_persona_gana_sobre_su_area(self):
        # Lo mas especifico manda, igual que en la resolucion de dominios.
        politica = Policy(
            area_actions={"ingenieria": "observar"}, user_actions={"u_dev": "bloquear"}
        )
        self.assertEqual(
            modo_de_la_persona("u_dev", "ingenieria", politica), "bloquear"
        )

    def test_quien_no_esta_nombrado_se_queda_con_la_politica_estricta(self):
        """La regla del ADR 0004: hay que nombrar para aflojar, nunca al reves.

        Asi, agregar un area a la lista no puede desproteger a nadie que no
        estuviera pensado.
        """

        politica = Policy(user_actions={"u_dev": "observar"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo()], politica, usuario="u_otro"),
            "block_content",
        )

    def test_una_excepcion_nunca_sube_la_severidad(self):
        # Solo rebaja un corte a un aviso. Nunca al reves: el evento se registra
        # igual y la empresa lo sigue viendo en el panel.
        politica = Policy(user_actions={"u_dev": "observar"})
        self.assertEqual(
            decidir_sobre("ai_approved", [hallazgo("email_address", "pii", "medium")], politica, usuario="u_dev"),
            "warn",
        )


class TestQuienGanaSobreQuien(unittest.TestCase):
    """El orden de precedencia. Es lo que hace que la politica sea predecible."""

    def test_un_dominio_prohibido_no_lo_afloja_una_excepcion_por_persona(self):
        politica = Policy(
            blocked_domains=frozenset({"deepseek.com"}),
            user_actions={"u_dev": "observar"},
        )
        self.assertEqual(
            decidir_sobre("ai_unapproved", [], politica, usuario="u_dev", host="deepseek.com"),
            "block_content",
        )

    def test_ni_una_aplicacion_en_modo_observar(self):
        politica = Policy(
            blocked_domains=frozenset({"deepseek.com"}),
            app_actions={"claude-code": "observar"},
        )
        self.assertEqual(
            decidir_sobre("ai_unapproved", [], politica, "claude-code", host="deepseek.com"),
            "block_content",
        )

    def test_ni_apagando_la_regla(self):
        politica = Policy(
            blocked_domains=frozenset({"deepseek.com"}),
            rule_actions={"aws_access_key_id": "off"},
        )
        self.assertEqual(
            decidir_sobre("ai_unapproved", [hallazgo()], politica, host="deepseek.com"),
            "block_content",
        )


class TestViajaEntera(unittest.TestCase):
    def test_los_cuatro_campos_van_y_vuelven(self):
        politica = Policy(
            blocked_domains=frozenset({"deepseek.com", "grok.com"}),
            rule_actions={"email_address": "off"},
            user_actions={"u_dev": "observar"},
            area_actions={"ingenieria": "observar"},
        )
        self.assertEqual(Policy.desde_dict(politica.a_dict()), politica)

    def test_una_politica_parcial_no_los_borra(self):
        # El bug que ya paso una vez: un backend viejo devolvia una politica
        # incompleta y los campos ausentes volvian al default del codigo.
        completa = Policy(blocked_domains=frozenset({"deepseek.com"}))
        mezclada = Policy.desde_dict({"tenant_id": "otra"}, completa)
        self.assertEqual(mezclada.blocked_domains, frozenset({"deepseek.com"}))


if __name__ == "__main__":
    unittest.main()
