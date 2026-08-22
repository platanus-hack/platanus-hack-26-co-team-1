"""Aprobar la herramienta no es aprobar la cuenta.

Todo el mercado permite o prohibe por DOMINIO. Si la empresa aprueba ChatGPT,
`chatgpt.com` queda en verde y la cuenta personal gratuita del empleado entra
por el mismo dominio con los mismos datos -- y es la que entrena con ellos.

La mitad de abajo de este archivo es la que sostiene que esto sea usable. La
comprobacion tiene dos formas faciles de arruinar el producto y las dos estan
probadas aca:

  1. Tratar "no vi ninguna credencial" como "cuenta personal". Un chat en el
     navegador se autentica con cookie y no manda `Authorization`; ChatGPT
     Enterprise tampoco. Con esa confusion, el uso sancionado se marca como
     fuga y Aegis dura un dia instalado.
  2. Encender la comprobacion sin que la empresa haya declarado sus cuentas.
     Con la lista vacia toda cuenta es ajena y el primer arranque bloquea a la
     empresa contra si misma.

Y la regla que no se negocia: la credencial no se guarda nunca, solo su huella.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aegis_agent import identidad
from aegis_agent.detect.types import EVIDENCE_MAX_LEN
from aegis_agent.policy import Policy
from tests.test_embudo import FakeFlow, FakeRequest, make_addon

LLAVE = "sk-ant-api03-secretodeverdad-no-debe-aparecer-jamas"


class TestDeDondeSaleLaIdentidad(unittest.TestCase):
    def test_una_cabecera_de_cuenta_explicita(self):
        quien = identidad.identidad({"chatgpt-account-id": "org-acme-123"})
        self.assertEqual(quien, "cuenta:org-acme-123")

    def test_la_organizacion_en_la_ruta_de_claude(self):
        """claude.ai no manda cabecera: lleva la organizacion en la URL."""

        quien = identidad.identidad(
            {}, "/api/organizations/9f2a1b3c-4d5e-6f70-8a9b-0c1d2e3f4a5b/chat"
        )
        self.assertEqual(quien, "cuenta:9f2a1b3c-4d5e-6f70-8a9b-0c1d2e3f4a5b")

    def test_una_credencial_da_su_huella(self):
        quien = identidad.identidad({"x-api-key": LLAVE})
        self.assertTrue(quien.startswith("clave:"))

    def test_da_igual_como_se_escriba_la_cabecera(self):
        """mitmproxy no distingue mayusculas y un dict si. Este modulo tampoco debe."""

        self.assertEqual(
            identidad.identidad({"Authorization": f"Bearer {LLAVE}"}),
            identidad.identidad({"authorization": f"bearer {LLAVE}"}),
        )

    def test_el_prefijo_bearer_no_cambia_la_huella(self):
        """La misma llave mandada por dos clientes distintos es la misma cuenta."""

        self.assertEqual(
            identidad.identidad({"authorization": f"Bearer {LLAVE}"}),
            identidad.identidad({"x-api-key": LLAVE}),
        )

    def test_dos_llaves_distintas_son_dos_cuentas(self):
        self.assertNotEqual(
            identidad.identidad({"x-api-key": LLAVE}),
            identidad.identidad({"x-api-key": "sk-ant-api03-la-de-otro"}),
        )

    def test_la_cuenta_explicita_le_gana_a_la_credencial(self):
        """Sobrevive a una rotacion de llaves; la huella no."""

        quien = identidad.identidad(
            {"openai-organization": "org-acme", "authorization": f"Bearer {LLAVE}"}
        )
        self.assertEqual(quien, "cuenta:org-acme")

    def test_authuser_cero_no_identifica_a_nadie(self):
        """Google manda 0 para la cuenta por defecto, que es todas las cuentas."""

        self.assertIsNone(identidad.identidad({"x-goog-authuser": "0"}))

    def test_un_request_sin_nada_no_identifica(self):
        self.assertIsNone(identidad.identidad({}, "/api/chat"))


class TestLaLlaveNuncaSeGuarda(unittest.TestCase):
    """El `Authorization` es lo mas sensible que lleva un request."""

    def test_la_huella_no_contiene_la_llave(self):
        quien = identidad.identidad({"authorization": f"Bearer {LLAVE}"})
        self.assertNotIn(LLAVE, quien)
        self.assertNotIn("sk-ant", quien)

    def test_la_huella_no_permite_reconstruir_la_llave(self):
        quien = identidad.identidad({"x-api-key": LLAVE})
        # Doce caracteres hex: suficiente para comparar, inservible para volver
        # atras.
        self.assertEqual(len(quien.removeprefix("clave:")), identidad.LARGO_DE_HUELLA)

    def test_la_huella_es_estable_entre_corridas(self):
        """Si cambiara, la politica de la empresa dejaria de reconocer su cuenta."""

        self.assertEqual(identidad.huella(LLAVE), identidad.huella(LLAVE))


class TestElVeredicto(unittest.TestCase):
    def test_una_cuenta_declarada_es_de_la_empresa(self):
        self.assertEqual(
            identidad.veredicto("cuenta:org-acme", frozenset({"cuenta:org-acme"})),
            identidad.CORPORATIVA,
        )

    def test_una_cuenta_que_nadie_declaro_es_ajena(self):
        self.assertEqual(
            identidad.veredicto("cuenta:org-personal", frozenset({"cuenta:org-acme"})),
            identidad.AJENA,
        )

    def test_sin_cuentas_declaradas_esto_no_opina(self):
        """El footgun: con la lista vacia toda cuenta seria ajena."""

        self.assertEqual(
            identidad.veredicto("cuenta:la-que-sea", frozenset()),
            identidad.SIN_IDENTIDAD,
        )

    def test_sin_identidad_no_es_lo_mismo_que_ajena(self):
        """El otro footgun: un chat en el navegador se autentica con cookie."""

        self.assertEqual(
            identidad.veredicto(None, frozenset({"cuenta:org-acme"})),
            identidad.SIN_IDENTIDAD,
        )

    def test_es_ajena_devuelve_la_identidad_para_el_panel(self):
        """Un booleano dejaria al panel diciendo "no autorizada" sin decir cual."""

        quien = identidad.es_ajena(
            {"chatgpt-account-id": "org-personal"}, "", frozenset({"cuenta:org-acme"})
        )
        self.assertEqual(quien, "cuenta:org-personal")

    def test_es_ajena_calla_cuando_la_cuenta_es_de_la_empresa(self):
        self.assertIsNone(
            identidad.es_ajena(
                {"chatgpt-account-id": "org-acme"}, "", frozenset({"cuenta:org-acme"})
            )
        )


class TestEnElAddon(unittest.TestCase):
    """La parte que decide: un dominio aprobado con cuenta ajena deja de estarlo."""

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"
        self.addon = make_addon(self.queue)

    def _correr(self, politica, cabeceras):
        self.addon.policy = politica
        flow = FakeFlow(
            FakeRequest("claude.ai", "/api/chat", b"hola", headers=cabeceras)
        )
        with patch("aegis_agent.proxy.addon.scan_payload") as escaneo:
            escaneo.return_value = type(
                "R", (), {"findings": [], "truncated": False, "views": 1}
            )()
            self.addon.request(flow)
        return flow

    def _eventos(self):
        crudo = self.queue.read_text(encoding="utf-8") if self.queue.exists() else ""
        import json

        return [json.loads(l) for l in crudo.splitlines() if l.strip()]

    def test_la_cuenta_de_la_empresa_pasa_sin_ruido(self):
        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        self._correr(politica, {"chatgpt-account-id": "org-acme"})
        self.assertEqual(self._eventos(), [])

    def test_con_block_encendido_la_cuenta_correcta_sigue_aprobada(self):
        """El bug que casi se cuela: degradar por tener `block` puesto y no por la cuenta.

        Sin este test, calcular la degradacion fuera del `if` pasaba
        inadvertido: no genera ningun evento, y sin embargo convierte la
        herramienta aprobada de la empresa entera en una no aprobada.
        """

        self.addon.policy = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        flow = FakeFlow(
            FakeRequest(
                "claude.ai", "/api/chat", b"hola",
                headers={"chatgpt-account-id": "org-acme"},
            )
        )
        self.assertEqual(
            self.addon._cuenta_de_la_empresa(flow, "claude.ai", "ai_approved"),
            "ai_approved",
        )

    def test_la_cuenta_personal_en_el_mismo_dominio_aprobado_se_registra(self):
        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        self._correr(politica, {"chatgpt-account-id": "org-personal"})
        eventos = self._eventos()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["detection"]["rule_id"], "cuenta_ajena")
        self.assertEqual(eventos[0]["destination"]["classification"], "ai_unapproved")

    def test_con_warn_el_envio_sigue_igual_pero_el_panel_lo_ve(self):
        """El default. La primera pregunta de una empresa es cuanta gente lo hace."""

        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="warn",
        )
        self._correr(politica, {"chatgpt-account-id": "org-personal"})
        eventos = self._eventos()
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["action"], "warned")
        # No se degrado: la herramienta sigue aprobada y nadie se frena.
        self.assertEqual(eventos[0]["destination"]["classification"], "ai_approved")

    def test_sin_cuentas_declaradas_no_cambia_nada(self):
        """Instalar Aegis no puede bloquear a la empresa contra si misma."""

        self._correr(Policy(foreign_account_action="block"), {"x-api-key": LLAVE})
        self.assertEqual(self._eventos(), [])

    def test_el_navegador_sin_credencial_no_se_acusa(self):
        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        self._correr(politica, {"cookie": "sesion=abc123"})
        self.assertEqual(self._eventos(), [])

    def test_el_evento_no_lleva_la_llave(self):
        """La evidencia es lo unico de esto que sale del equipo."""

        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        self._correr(politica, {"authorization": f"Bearer {LLAVE}"})
        crudo = self.queue.read_text(encoding="utf-8")
        self.assertNotIn(LLAVE, crudo)
        self.assertNotIn("sk-ant", crudo)

    def test_la_evidencia_respeta_el_contrato(self):
        """Un uuid de organizacion es mas largo que el limite del contrato."""

        largo = "cuenta:" + "a1b2c3d4-" * 6
        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme"}),
            foreign_account_action="block",
        )
        self._correr(politica, {"chatgpt-account-id": largo.removeprefix("cuenta:")})
        eventos = self._eventos()
        self.assertLessEqual(
            len(eventos[0]["detection"]["evidence"]), EVIDENCE_MAX_LEN
        )


class TestLaPoliticaViaja(unittest.TestCase):
    def test_los_campos_sobreviven_la_ida_y_vuelta(self):
        politica = Policy(
            corporate_accounts=frozenset({"cuenta:org-acme", "clave:abc123def456"}),
            foreign_account_action="block",
        )
        vuelta = Policy.desde_dict(politica.a_dict())
        self.assertEqual(vuelta.corporate_accounts, politica.corporate_accounts)
        self.assertEqual(vuelta.foreign_account_action, "block")

    def test_un_backend_viejo_no_borra_las_cuentas(self):
        """Lo que el dict no nombra se conserva (ver desde_dict)."""

        base = Policy(corporate_accounts=frozenset({"cuenta:org-acme"}))
        vuelta = Policy.desde_dict({"tenant_id": "acme"}, base=base)
        self.assertEqual(vuelta.corporate_accounts, frozenset({"cuenta:org-acme"}))


if __name__ == "__main__":
    unittest.main()
