"""Una credencial que viaja hacia su propio dueno no es una fuga.

Suena obvio dicho asi, y sin embargo es lo que rompe a un DLP ingenuo apenas se
instala. Se descubrio en vivo: con Aegis en el medio, Claude Code no podia ni
autenticarse, porque su propio token hacia api.anthropic.com se leia como una
filtracion.

La distincion que importa es la direccion. sk-ant-... hacia api.anthropic.com es
trabajo; el mismo sk-ant-... hacia chatgpt.com es una fuga.
"""

import unittest

from aegis_agent.detect.entropy import looks_random
from aegis_agent.detect.owners import (
    DUENOS,
    es_ruta_de_autenticacion,
    es_su_dueno,
    exento,
)


class TestCredencialHaciaSuDueno(unittest.TestCase):
    def test_cada_credencial_pasa_hacia_su_servicio(self):
        casos = {
            "anthropic_api_key": "api.anthropic.com",
            "openai_api_key": "api.openai.com",
            "github_token": "api.github.com",
            "slack_token": "hooks.slack.com",
            "stripe_secret_key": "api.stripe.com",
            "huggingface_token": "huggingface.co",
            "aws_access_key_id": "s3.us-east-1.amazonaws.com",
        }
        for regla, host in casos.items():
            with self.subTest(regla=regla):
                self.assertTrue(es_su_dueno(regla, host))

    def test_la_misma_credencial_hacia_otro_lado_si_es_fuga(self):
        for regla in DUENOS:
            with self.subTest(regla=regla):
                self.assertFalse(es_su_dueno(regla, "chatgpt.com"))
                self.assertFalse(es_su_dueno(regla, "asistente-raro.co"))

    def test_los_subdominios_del_dueno_cuentan(self):
        for host in ("api.anthropic.com", "console.anthropic.com", "platform.claude.com"):
            with self.subTest(host=host):
                self.assertTrue(es_su_dueno("anthropic_api_key", host))

    def test_la_app_web_del_proveedor_no_es_su_dueno(self):
        # Pegar tu llave en el chat web no es usarla: es la fuga que buscamos.
        self.assertFalse(es_su_dueno("openai_api_key", "chatgpt.com"))
        self.assertFalse(es_su_dueno("anthropic_api_key", "claude.ai"))

    def test_un_dominio_parecido_no_cuenta(self):
        # anthropic.com.attacker.co no es anthropic.com.
        self.assertFalse(es_su_dueno("anthropic_api_key", "anthropic.com.attacker.co"))
        self.assertFalse(es_su_dueno("github_token", "notgithub.com"))


class TestSaludoDeAutenticacion(unittest.TestCase):
    """Un token sin dueno reconocible se perdona solo donde es el pasaje."""

    def test_las_rutas_de_login_se_reconocen(self):
        for ruta in ("/v1/oauth/token", "/auth/login", "/api/session", "/.well-known/x"):
            with self.subTest(ruta=ruta):
                self.assertTrue(es_ruta_de_autenticacion(ruta))

    def test_una_ruta_de_conversacion_no_lo_es(self):
        for ruta in ("/v1/messages", "/backend-api/conversation", "/api/chat"):
            with self.subTest(ruta=ruta):
                self.assertFalse(es_ruta_de_autenticacion(ruta))

    def test_un_jwt_en_el_login_pasa(self):
        self.assertTrue(exento("jwt", "api.anthropic.com", "/v1/oauth/token"))

    def test_un_jwt_dentro_de_un_prompt_no_pasa(self):
        self.assertFalse(exento("jwt", "api.anthropic.com", "/v1/messages"))

    def test_una_llave_de_aws_no_se_perdona_ni_en_el_login(self):
        # El saludo de autenticacion perdona el token propio, no cualquier cosa.
        self.assertFalse(exento("aws_access_key_id", "api.anthropic.com", "/v1/oauth/token"))


class TestMarcadoNoEsCredencial(unittest.TestCase):
    """El falso positivo que bloqueaba sesiones limpias de Claude Code."""

    def test_un_fragmento_de_codigo_en_markdown(self):
        for valor in ("`git-commit-abcdef`", "<TU_API_KEY_ACA>", "${SECRET_TOKEN}"):
            with self.subTest(valor=valor):
                self.assertFalse(looks_random(valor))

    def test_una_plantilla_no_es_una_credencial(self):
        for valor in ("{{ secreto }}", "(reemplazar-esto)", "[valor-aqui]"):
            with self.subTest(valor=valor):
                self.assertFalse(looks_random(valor))

    def test_una_credencial_de_verdad_sigue_detectandose(self):
        self.assertTrue(looks_random("xK9mQ2wZr7Lp4Nv8Ty"))
        self.assertTrue(looks_random("wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY"))


if __name__ == "__main__":
    unittest.main()
