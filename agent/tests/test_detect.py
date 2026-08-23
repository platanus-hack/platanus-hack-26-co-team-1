import unittest

from aegis_agent.detect import scan
from aegis_agent.detect.entropy import luhn_valid, shannon_entropy
from aegis_agent.detect.redaction import redact
from aegis_agent.detect.types import EVIDENCE_MAX_LEN, EVIDENCE_VISIBLE_PREFIX

# Credenciales sinteticas con el formato correcto pero sin valor real.
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
ANTHROPIC_KEY = "sk-ant-api03-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"
# Los valores de prueba tienen que parecerse a un token de verdad, y no ser
# "a" * 36. Desde que existe el filtro de placeholder, una corrida de
# caracteres identicos ES la senal de que algo es una plantilla: un fixture
# perezoso deja de probar la regla y empieza a probar el filtro.
GITHUB_TOKEN = "ghp_" + "16kQ2vB9xTdLm4WpRc7YsZaE0hNjUf3G8oIt"
VISA_TEST = "4111111111111111"


class TestSecretRules(unittest.TestCase):
    def test_detecta_llave_de_aws(self):
        findings = scan(f"usa esta llave {AWS_KEY} para el deploy")
        self.assertEqual([f.rule_id for f in findings], ["aws_access_key_id"])
        self.assertEqual(findings[0].severity, "critical")

    def test_detecta_llave_de_anthropic_sin_confundirla_con_openai(self):
        findings = scan(f"ANTHROPIC_API_KEY={ANTHROPIC_KEY}")
        rule_ids = {f.rule_id for f in findings}
        self.assertIn("anthropic_api_key", rule_ids)
        self.assertNotIn("openai_api_key", rule_ids)

    def test_detecta_token_de_github(self):
        findings = scan(f"token: {GITHUB_TOKEN}")
        self.assertIn("github_token", {f.rule_id for f in findings})

    def test_detecta_cadena_de_conexion(self):
        findings = scan("DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod")
        self.assertIn("db_connection_string", {f.rule_id for f in findings})

    def test_detecta_bloque_de_llave_privada(self):
        findings = scan("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...")
        self.assertIn("private_key_block", {f.rule_id for f in findings})

    def test_texto_limpio_no_genera_hallazgos(self):
        prompt = (
            "Necesito que me ayudes a redactar el copy de la campana de "
            "septiembre para redes sociales, con tono cercano."
        )
        self.assertEqual(scan(prompt), [])

    def test_texto_vacio_no_revienta(self):
        self.assertEqual(scan(""), [])


class TestFalsePositives(unittest.TestCase):
    def test_password_en_lenguaje_natural_no_es_secreto(self):
        findings = scan("La password es la misma de siempre, preguntale a Ana")
        self.assertEqual(findings, [])

    def test_password_con_alta_entropia_si_es_secreto(self):
        findings = scan('password = "xK9$mQ2wZr7Lp4Nv"')
        self.assertIn("generic_secret_assignment", {f.rule_id for f in findings})

    def test_numero_largo_que_no_pasa_luhn_no_es_tarjeta(self):
        findings = scan("el radicado es 1234567812345678")
        self.assertEqual(findings, [])

    def test_numero_que_pasa_luhn_si_es_tarjeta(self):
        findings = scan(f"pago con {VISA_TEST}")
        self.assertIn("credit_card", {f.rule_id for f in findings})


class TestOverlap(unittest.TestCase):
    def test_una_llave_dentro_de_una_asignacion_se_reporta_una_sola_vez(self):
        findings = scan(f"aws_secret = {AWS_KEY}")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "aws_access_key_id")

    def test_hallazgos_vienen_ordenados_por_severidad(self):
        findings = scan(f"correo ana@acme.co y llave {AWS_KEY}")
        self.assertEqual(findings[0].severity, "critical")


class TestRedaction(unittest.TestCase):
    """Estos tests son el invariante 1 y 3 del contrato de datos.

    Si alguno se cae, el agente esta filtrando hacia el backend justo lo que el
    producto promete no filtrar.
    """

    def test_la_evidencia_nunca_contiene_el_secreto_completo(self):
        findings = scan(f"llave {AWS_KEY}")
        self.assertNotIn(AWS_KEY, findings[0].evidence)

    def test_la_evidencia_respeta_el_tope_de_longitud(self):
        for text in (f"llave {AWS_KEY}", f"token {GITHUB_TOKEN}", f"key {ANTHROPIC_KEY}"):
            for finding in scan(text):
                self.assertLessEqual(len(finding.evidence), EVIDENCE_MAX_LEN)

    def test_solo_el_prefijo_queda_visible(self):
        redacted = redact(AWS_KEY)
        self.assertTrue(redacted.startswith(AWS_KEY[:EVIDENCE_VISIBLE_PREFIX]))
        self.assertEqual(set(redacted[EVIDENCE_VISIBLE_PREFIX:]), {"*"})

    def test_la_pii_no_muestra_ninguna_muestra(self):
        findings = scan("escribeme a juan.perez@acme.co")
        self.assertEqual(findings[0].evidence, "<email>")


class TestEntropy(unittest.TestCase):
    def test_entropia_de_texto_vacio(self):
        self.assertEqual(shannon_entropy(""), 0.0)

    def test_una_clave_tiene_mas_entropia_que_una_frase(self):
        clave = shannon_entropy("xK9mQ2wZr7Lp4Nv8Ty3Ub6Ic")
        frase = shannon_entropy("la reunion es el martes a las tres")
        self.assertGreater(clave, frase)

    def test_luhn_rechaza_longitudes_invalidas(self):
        self.assertFalse(luhn_valid("411111"))


if __name__ == "__main__":
    unittest.main()
