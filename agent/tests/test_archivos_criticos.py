"""Un archivo puede ser critico por lo que ES, no por lo que dice.

Un volcado de base de datos es binario y no tiene una sola palabra que una regla
de texto pueda encontrar. Un .env con FOO=bar no dispara ninguna heuristica de
entropia y sigue siendo la configuracion de produccion. Esto se decide antes de
leer una linea: por el nombre del adjunto y por su firma binaria.
"""

import unittest

from aegis_agent.detect.files import clasificar_nombre, nombres_adjuntos, scan_files
from aegis_agent.detect.payload import scan_payload


def multipart(nombre_archivo: str, contenido: bytes = b"contenido") -> bytes:
    return (
        b"--X\r\n"
        b'Content-Disposition: form-data; name="file"; filename="'
        + nombre_archivo.encode()
        + b'"\r\nContent-Type: application/octet-stream\r\n\r\n'
        + contenido
        + b"\r\n--X--\r\n"
    )


def reglas(cuerpo: bytes) -> set[str]:
    return {f.rule_id for f in scan_payload(cuerpo).findings}


class TestNombresCriticos(unittest.TestCase):
    def test_variantes_de_env(self):
        for nombre in (".env", ".env.production", ".env.local", "env.prod", "api.env"):
            with self.subTest(nombre=nombre):
                self.assertEqual(clasificar_nombre(nombre), ("secret", "env"))

    def test_llaves_y_certificados(self):
        casos = {
            "id_rsa": "llave_ssh",
            "id_ed25519": "llave_ssh",
            "server.pem": "certificado",
            "private.key": "llave_privada",
            "almacen.p12": "almacen_de_llaves",
            "bovedas.kdbx": "gestor_de_contrasenas",
        }
        for nombre, tipo in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(clasificar_nombre(nombre), ("secret", tipo))

    def test_bases_de_datos_y_respaldos(self):
        for nombre in ("clientes.sql", "prod.dump", "app.sqlite3", "datos.db", "todo.bak"):
            with self.subTest(nombre=nombre):
                categoria, _ = clasificar_nombre(nombre)
                self.assertEqual(categoria, "internal_data")

    def test_infraestructura(self):
        for nombre in ("terraform.tfstate", "prod.tfvars", "kubeconfig", ".pgpass"):
            with self.subTest(nombre=nombre):
                self.assertIsNotNone(clasificar_nombre(nombre))

    def test_la_ruta_completa_no_confunde(self):
        self.assertEqual(clasificar_nombre("C:\\proyecto\\config\\.env"), ("secret", "env"))
        self.assertEqual(clasificar_nombre("/home/juan/.ssh/id_rsa"), ("secret", "llave_ssh"))

    def test_archivos_de_trabajo_normales_no_son_criticos(self):
        for nombre in (
            "informe.pdf",
            "campana.pptx",
            "logo.png",
            "notas.txt",
            "presupuesto.xlsx",
            "index.html",
            "main.py",
        ):
            with self.subTest(nombre=nombre):
                self.assertIsNone(clasificar_nombre(nombre))


class TestFirmasBinarias(unittest.TestCase):
    """El archivo puede llegar renombrado y la cabecera lo delata igual."""

    def test_sqlite_renombrado_a_txt(self):
        cuerpo = multipart("notas.txt", b"SQLite format 3\x00" + b"\x00" * 300)
        self.assertIn("archivo_critico_por_firma", reglas(cuerpo))

    def test_volcado_de_postgres_renombrado(self):
        cuerpo = multipart("reporte.doc", b"PGDMP" + b"\x00" * 200)
        self.assertIn("archivo_critico_por_firma", reglas(cuerpo))

    def test_llave_ssh_renombrada(self):
        cuerpo = multipart("licencia.txt", b"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA")
        self.assertIn("archivo_critico_por_firma", reglas(cuerpo))

    def test_un_pdf_de_verdad_no_dispara(self):
        cuerpo = multipart("informe.pdf", b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n")
        self.assertEqual(reglas(cuerpo), set())


class TestDeteccionAntesDeLeerElContenido(unittest.TestCase):
    def test_un_env_sin_nada_sensible_adentro_se_bloquea_igual(self):
        # FOO=bar no dispara entropia, formato ni palabra clave. El archivo si.
        cuerpo = multipart(".env", b"FOO=bar\nDEBUG=true\n")
        self.assertIn("archivo_critico", reglas(cuerpo))

    def test_una_base_vacia_se_bloquea_igual(self):
        cuerpo = multipart("respaldo.sqlite", b"\x00" * 500)
        self.assertIn("archivo_critico", reglas(cuerpo))

    def test_el_hallazgo_es_critico_y_bloquea(self):
        from aegis_agent.policy import Policy, decide

        hallazgos = scan_payload(multipart(".env", b"FOO=bar")).findings
        categorias = {f.category for f in hallazgos}
        self.assertEqual(decide("ai_approved", categorias, Policy()), "block_content")

    def test_la_evidencia_no_lleva_el_nombre_del_archivo(self):
        # "clientes-bancolombia-2026.sql" ya dice demasiado por si mismo.
        hallazgos = scan_payload(multipart("clientes-bancolombia-2026.sql")).findings
        for hallazgo in hallazgos:
            with self.subTest(regla=hallazgo.rule_id):
                self.assertNotIn("bancolombia", hallazgo.evidence)
                self.assertNotIn("clientes", hallazgo.evidence)


class TestExtraccionDeNombres(unittest.TestCase):
    def test_con_comillas(self):
        self.assertEqual(nombres_adjuntos('filename="a.env"'), ["a.env"])

    def test_sin_comillas(self):
        self.assertEqual(nombres_adjuntos("filename=a.sql; x=1"), ["a.sql"])

    def test_varios_adjuntos_en_un_envio(self):
        texto = 'filename="uno.pdf" ... filename="dos.sql"'
        self.assertEqual(nombres_adjuntos(texto), ["uno.pdf", "dos.sql"])

    def test_sin_adjuntos(self):
        self.assertEqual(scan_files(b"", "solo texto"), [])


if __name__ == "__main__":
    unittest.main()
