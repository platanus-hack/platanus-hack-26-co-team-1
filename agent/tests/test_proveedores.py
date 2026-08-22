"""Credenciales por proveedor, con los huecos que encontro la bateria.

Todos los valores son falsos: formato real, contenido inventado o tomado de la
documentacion publica del proveedor. Ninguno autentica en ningun lado.

Los tres primeros casos de TestLimitesDePalabra son los que se escapaban en la
corrida contra el proxy, y por la misma razon: el limite de palabra no casa
cuando el nombre de la variable lleva guiones bajos.
"""

import json
import unittest

from aegis_agent.detect.payload import scan_payload


def reglas(texto: str) -> set[str]:
    return {f.rule_id for f in scan_payload(texto.encode()).findings}


def como_prompt(texto: str) -> set[str]:
    """Igual que arriba pero dentro de un JSON, como viaja de verdad."""

    cuerpo = json.dumps({"messages": [{"content": f"Revisa esto: {texto}"}]})
    return {f.rule_id for f in scan_payload(cuerpo.encode()).findings}


class TestProveedores(unittest.TestCase):
    # Los valores se parecen a un token de verdad a proposito. Antes eran
    # "f" * 64 y "Z" * 60, y desde que existe el filtro de placeholder eso ya no
    # se puede: una corrida de caracteres identicos ES la senal de que algo es
    # una plantilla, asi que el fixture perezoso dejaba de probar la regla y
    # empezaba a probar el filtro. Que estos cuatro tests se pusieran rojos al
    # agregar el filtro fue la senal correcta, no un problema del filtro.
    CASOS = {
        "sendgrid_api_key": "SENDGRID_API_KEY=SG.7bQ2xVn9TzKm4RpLc8Ys_A."
        + "e5WgHj1NfDu7ZaKq3XcMv0RtYb8SpLn6JiOe2Uw",
        "mailgun_api_key": "MAILGUN_KEY=key-9c3f7a1e5b8d2064af91e3c7d5028b46",
        "digitalocean_token": "DO_TOKEN=dop_v1_"
        + "3f9a7c1e5d8b0462af31e9c7d5028b46129e4fa7c3d85b016e9a2f7c4d80b3512",
        "huggingface_token": "HF_TOKEN=hf_ABcdEFghIJklMNopQRstUVwxYZ012345",
        "azure_storage_key": "AccountName=acme;AccountKey=W7bQx2Vn9TzKm4RpLc8"
        + "YsAe5WgHj1NfDu7ZaKq3XcMv0RtYb8SpLn6JiOe2Uw4h==;",
        "twilio_credential": "TWILIO_SID=AC" + "9f8e7d6c5b4a3210fedcba9876543210",
    }

    def test_cada_proveedor_tiene_su_regla(self):
        for regla, texto in self.CASOS.items():
            with self.subTest(regla=regla):
                self.assertIn(regla, reglas(texto))

    def test_tambien_dentro_de_un_prompt(self):
        for regla, texto in self.CASOS.items():
            with self.subTest(regla=regla):
                self.assertTrue(como_prompt(texto), f"{regla} no se ve dentro del JSON")


class TestLimitesDePalabra(unittest.TestCase):
    """El nombre de la variable lleva guiones bajos y eso rompia el limite."""

    def test_aws_secret_access_key(self):
        texto = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        self.assertIn("generic_secret_assignment", reglas(texto))

    def test_twilio_auth_token(self):
        texto = "TWILIO_AUTH_TOKEN=9f8e7d6c5b4a3210fedcba9876543210"
        self.assertIn("generic_secret_assignment", reglas(texto))

    def test_mailgun_private_key(self):
        texto = "MAILGUN_PRIVATE_API_KEY=abcdef0123456789abcdef0123456789"
        self.assertIn("generic_secret_assignment", reglas(texto))


class TestComillasEscapadas(unittest.TestCase):
    """El prompt viaja dentro de otro JSON y llega con las comillas escapadas."""

    def test_una_contrasena_entre_comillas_escapadas(self):
        self.assertIn("generic_secret_assignment", como_prompt('password = "xK9mQ2wZr7Lp4Nv8Ty"'))

    def test_una_llave_entre_comillas_escapadas(self):
        self.assertIn(
            "generic_secret_assignment", como_prompt('api_key: "aB3dE5fG7hJ9kL1mN3pQ5"')
        )


class TestSinFalsosPositivos(unittest.TestCase):
    def test_hablar_de_credenciales_no_es_filtrarlas(self):
        for texto in (
            "Donde configuro el api key de SendGrid?",
            "El token expiro, hay que renovarlo",
            "password: la de siempre",
            "Necesito el AccountKey pero no lo tengo a mano",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(reglas(texto), set())

    def test_un_identificador_corto_no_es_un_secreto(self):
        self.assertEqual(reglas("order_token=A1B2C3"), set())


if __name__ == "__main__":
    unittest.main()
