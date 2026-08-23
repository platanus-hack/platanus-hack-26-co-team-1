"""Datos de la empresa: lo que la gente pega de verdad.

Un archivo .env es el caso facil y el menos frecuente. Lo que sale todos los dias
son consultas, tablas, exports de clientes y documentos internos, y ese material
no tiene un formato reconocible como el de una API key.
"""

import unittest

from aegis_agent.detect.payload import BULK_PII_THRESHOLD, scan_payload
from aegis_agent.policy import Policy, decide

POLICY = Policy()


def rules(text: str) -> set[str]:
    return {finding.rule_id for finding in scan_payload(text.encode()).findings}


def categories(text: str) -> set[str]:
    return {finding.category for finding in scan_payload(text.encode()).findings}


class TestBasesDeDatos(unittest.TestCase):
    def test_volcado_de_mysql(self):
        dump = "-- MySQL dump 10.13  Distrib 8.0.32\n-- Host: prod    Database: acme"
        self.assertIn("sql_dump_header", rules(dump))

    def test_volcado_de_postgres(self):
        self.assertIn("sql_dump_header", rules("-- PostgreSQL database dump"))

    def test_filas_con_datos_reales(self):
        sql = "INSERT INTO clientes (id, nombre, correo) VALUES (1, 'Ana', 'ana@acme.co');"
        self.assertIn("sql_insert_rows", rules(sql))

    def test_esquema_con_columnas_sensibles(self):
        sql = "CREATE TABLE empleados (id serial, nombre text, salario numeric);"
        self.assertIn("sql_schema_sensitive", rules(sql))

    def test_resultado_de_consulta_como_export(self):
        export = "nombre;email;telefono;ciudad\nAna;ana@acme.co;3001234567;Bogota"
        self.assertIn("csv_pii_export", rules(export))

    def test_export_con_cabecera_en_ingles(self):
        export = "name,email,phone,city\nAna,ana@acme.co,3001234567,Bogota"
        self.assertIn("csv_pii_export", rules(export))


class TestDatosPersonales(unittest.TestCase):
    def test_cedula_colombiana_con_contexto(self):
        self.assertIn("latam_national_id", rules("El cliente con CC 1.023.456.789"))

    def test_nit_de_empresa(self):
        self.assertIn("latam_national_id", rules("Factura para NIT 900.123.456-7"))

    def test_documentos_de_otros_paises(self):
        for texto in ("RUT 12.345.678-9", "CURP GOMA850101HDFRRN04", "CPF 123.456.789-00"):
            with self.subTest(texto=texto):
                self.assertIn("latam_national_id", rules(texto))

    def test_cuenta_bancaria_iban(self):
        self.assertIn("iban", rules("Transferir a ES91 2100 0418 4502 0005 1332"))


class TestVolumen(unittest.TestCase):
    """La senal esta en la cantidad, no en el dato.

    Ninguna regla individual distingue un correo mencionado en una frase de un
    correo que es la fila 300 de un export. La diferencia es cuantos hay.
    """

    def test_una_base_de_clientes_se_detecta_como_export(self):
        listado = "\n".join(f"cliente{i}@acme.co" for i in range(BULK_PII_THRESHOLD + 5))
        found = rules(listado)
        self.assertIn("bulk_pii_export", found)
        self.assertIn("internal_data", categories(listado))

    def test_mencionar_dos_correos_no_es_un_export(self):
        texto = "Escribile a ana@acme.co y ponme en copia a juan@acme.co"
        self.assertNotIn("bulk_pii_export", rules(texto))

    def test_el_conteo_no_se_duplica_entre_vistas(self):
        import base64

        listado = "\n".join(f"cliente{i}@acme.co" for i in range(BULK_PII_THRESHOLD + 5))
        doble = listado + "\n" + base64.b64encode(listado.encode()).decode()
        bulk = [
            f for f in scan_payload(doble.encode()).findings if f.rule_id == "bulk_pii_export"
        ]
        self.assertEqual(len(bulk), 1)


class TestDocumentosInternos(unittest.TestCase):
    def test_marcador_de_confidencialidad(self):
        for texto in (
            "ACTA CONFIDENCIAL de la junta directiva",
            "Este documento es de uso interno",
            "Company Confidential - do not distribute",
        ):
            with self.subTest(texto=texto):
                self.assertIn("confidentiality_marker", rules(texto))


class TestFalsosPositivos(unittest.TestCase):
    """Cada uno de estos, si falla, es una razon para desinstalar Aegis."""

    def test_consulta_preparada_no_es_una_fuga(self):
        sql = "INSERT INTO pedidos (id, total) VALUES (?, ?)"
        self.assertNotIn("sql_insert_rows", rules(sql))

    def test_consulta_con_placeholders_con_nombre(self):
        sql = "INSERT INTO pedidos (id, total) VALUES (:id, :total)"
        self.assertNotIn("sql_insert_rows", rules(sql))

    def test_esquema_sin_columnas_sensibles(self):
        sql = "CREATE TABLE productos (id serial, nombre text, precio numeric);"
        self.assertEqual(rules(sql), set())

    def test_la_palabra_documento_sin_numero_no_es_una_cedula(self):
        self.assertNotIn("latam_national_id", rules("adjunto el documento del proyecto"))

    def test_una_cabecera_sin_datos_personales_no_es_un_export(self):
        self.assertNotIn("csv_pii_export", rules("producto,cantidad,precio,bodega"))

    def test_pregunta_tecnica_normal(self):
        pregunta = (
            "Como optimizo esta consulta? SELECT * FROM pedidos WHERE fecha > "
            "'2026-01-01' ORDER BY total DESC LIMIT 10"
        )
        self.assertEqual(rules(pregunta), set())


class TestPolitica(unittest.TestCase):
    def test_los_datos_internos_se_bloquean_igual_que_un_secreto(self):
        self.assertEqual(decide("ai_approved", {"internal_data"}, POLICY), "block_content")

    def test_un_dato_personal_suelto_solo_advierte(self):
        self.assertEqual(decide("ai_approved", {"pii"}, POLICY), "warn")


if __name__ == "__main__":
    unittest.main()
