"""El filtro de placeholder: que no corte lo que es una plantilla, y que no se
lleve puesto lo que es un secreto de verdad.

La mitad de abajo es la que importa. Un filtro de falsos positivos en un producto
de seguridad es una regla que APAGA otra regla: si se equivoca, deja salir la
credencial que el motor ya habia visto. Por eso hay mas casos negativos que
positivos, y por eso estan los casos borde de corridas cortas.
"""

from __future__ import annotations

import json
import unittest

from aegis_agent.detect.contexto import es_marca_de_documento, es_tarjeta_de_verdad
from aegis_agent.detect.payload import scan_payload
from aegis_agent.detect.placeholders import es_placeholder


def reglas(texto: str) -> set[str]:
    """Como llega de verdad: dentro del JSON de una conversacion."""

    cuerpo = json.dumps({"messages": [{"role": "user", "content": texto}]})
    return {f.rule_id for f in scan_payload(cuerpo.encode()).findings}


class TestEsPlaceholder(unittest.TestCase):
    PLANTILLAS = (
        "sk-proj-XXXXXXXXXXXXXXXXXXXX",
        "XXXXXXXXXXXX",
        "000000000000",
        "************",
        "REEMPLAZAR_CON_TU_TOKEN",
        "YOUR_API_KEY_HERE",
        "tu-clave-aca",
        "changeme",
        "CHANGE_ME_PLEASE",
        "insert_token_here",
        "TODO_PONER_LA_CLAVE",
        "placeholder",
        "REDACTED",
        "postgres://user:password@localhost:5432/db",
        "mysql://root:root@localhost/midb",
        "mongodb://admin:admin@db:27017",
    )

    def test_las_plantillas_se_reconocen(self):
        for valor in self.PLANTILLAS:
            with self.subTest(valor=valor):
                self.assertTrue(es_placeholder(valor), f"{valor} deberia ser plantilla")

    # Lo que NO puede caer en el filtro. Cada uno es un secreto real que, si el
    # filtro lo toma por plantilla, sale del equipo sin que nadie se entere.
    SECRETOS = (
        "AKIAIOSFODNN7EXAMPLE",  # la llave de ejemplo de AWS: contiene EXAMPLE
        "AKIA4F9C2E7B1D8A3G5H",
        "ghp_16kQ2vB9xTdLm4WpRc7YsZaE0hNjUf3G8oIt",
        "sk-ant-api03-7bQ2xVn9TzKm4RpLc8YsAe5WgHj1NfDu7ZaKq3XcMv0RtYb",
        "Verano2026Bogota",
        "Sup3rS3cret",
        "Temporal#2026",
        "postgres://prod_user:Xk8fRm2Qw9@db.acme.co:5432/nomina",
        # Un tunel de produccion contra localhost: host generico pero credencial
        # de verdad. Es la razon por la que el filtro de conexion pide LAS DOS.
        "postgres://acme_app:Zt4Kq9Wm2Rb@localhost:5432/prod",
        # Credenciales genericas pero host real: idem al reves.
        "postgres://admin:admin@db.produccion.acme.co:5432/clientes",
        # Una corrida corta dentro de un token largo NO alcanza. Es el caso que
        # decide la calibracion: si alcanzara, un token real con dos caracteres
        # repetidos por casualidad quedaria invisible.
        "ghp_16kQ2vaaaaaaB9xTdLm4WpRc7YsZaE0hNjUf",
    )

    def test_los_secretos_de_verdad_no_caen_en_el_filtro(self):
        for valor in self.SECRETOS:
            with self.subTest(valor=valor):
                self.assertFalse(
                    es_placeholder(valor), f"{valor} NO es plantilla y el filtro lo tomo"
                )


class TestFalsosPositivosMedidos(unittest.TestCase):
    """Las cinco frases que la auditoria del 22-ago-2026 midio como falsos positivos.

    Las dos primeras eran de categoria ``secret``, que CORTA el envio: un
    desarrollador preguntando por su propio ``.env.example`` se comia un 403.
    """

    def test_placeholder_en_la_documentacion_no_dispara(self):
        self.assertEqual(
            reglas("en la documentacion usan sk-proj-XXXXXXXXXXXXXXXXXXXX como ejemplo"),
            set(),
        )

    def test_env_example_no_dispara(self):
        self.assertEqual(
            reglas("el .env.example tiene DATABASE_URL=postgres://user:password@localhost:5432/db"),
            set(),
        )

    def test_numero_de_factura_no_es_tarjeta(self):
        self.assertNotIn(
            "credit_card", reglas("el numero de la factura es 4111111111111111")
        )

    def test_pregunta_sobre_word_no_es_documento_confidencial(self):
        self.assertNotIn(
            "confidentiality_marker",
            reglas("como configuro el confidencial en el pie de pagina?"),
        )

    def test_lista_de_telefonos_no_son_tarjetas(self):
        texto = "\n".join(f"+57 30{i}1234567" for i in range(20))
        self.assertNotIn("credit_card", reglas(texto))


class TestLoQueSigueDetectando(unittest.TestCase):
    """El contraveneno: lo de arriba no puede haber apagado la deteccion real."""

    def test_la_cadena_de_conexion_real_sigue_cortando(self):
        self.assertIn(
            "db_connection_string",
            reglas("DATABASE_URL=postgres://acme:Xk8fRm2Qw9@db.acme.co:5432/prod"),
        )

    def test_la_tarjeta_real_sigue_detectandose(self):
        self.assertIn(
            "credit_card", reglas("le cobramos a la tarjeta 4111111111111111")
        )

    def test_el_documento_marcado_sigue_detectandose(self):
        self.assertIn(
            "confidentiality_marker",
            reglas("CONFIDENCIAL - uso interno\nProyeccion de ventas 2027"),
        )

    def test_la_llave_de_aws_de_la_documentacion_sigue_detectandose(self):
        """Contiene la palabra EXAMPLE y aun asi tiene que verse.

        Si "example" alcanzara para descartar un valor, cualquiera saca una
        credencial de verdad agregandole ese sufijo. Es el bypass mas facil que
        podria tener el producto y por eso esa palabra no esta en el filtro.
        """

        self.assertIn("aws_access_key_id", reglas("mi llave es AKIAIOSFODNN7EXAMPLE"))


class TestValidadoresDeContexto(unittest.TestCase):
    def test_ventana_corta_a_proposito(self):
        """Con una ventana larga, cualquier texto de oficina tiene "factura"."""

        texto = "la factura del mes pasado ya se pago, y aparte de eso, sobre otro tema completamente distinto, la tarjeta es 4111111111111111"
        inicio = texto.index("4111")
        self.assertTrue(es_tarjeta_de_verdad(texto, inicio, inicio + 16))

    def test_la_pregunta_se_detecta_en_cualquiera_de_los_dos_lados(self):
        for texto in (
            "como pongo el confidencial",
            "el confidencial, donde se configura?",
        ):
            with self.subTest(texto=texto):
                inicio = texto.index("confidencial")
                self.assertFalse(
                    es_marca_de_documento(texto, inicio, inicio + len("confidencial"))
                )


if __name__ == "__main__":
    unittest.main()
