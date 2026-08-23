"""Suite adversarial: cada test es una forma conocida de esquivar un DLP.

El criterio es duro a proposito. Si alguno de estos se cae, el producto se puede
esquivar sin proponerselo: comprimir un archivo o adjuntar un .docx no es una
tecnica de atacante, es el martes de cualquier empleado.
"""

import base64
import gzip
import io
import unittest
import zipfile

from aegis_agent.detect.payload import MAX_INSPECT_BYTES, scan_payload

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
ANTHROPIC_KEY = "sk-ant-api03-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6"


def rules(body: bytes, query: str = "") -> set[str]:
    return {finding.rule_id for finding in scan_payload(body, query).findings}


class TestEncodingEvasion(unittest.TestCase):
    def test_texto_plano(self):
        self.assertIn("aws_access_key_id", rules(f"llave {AWS_KEY}".encode()))

    def test_base64(self):
        payload = base64.b64encode(f"AWS_ACCESS_KEY_ID={AWS_KEY}".encode())
        self.assertIn("aws_access_key_id", rules(payload))

    def test_base64_doble(self):
        once = base64.b64encode(f"key {AWS_KEY}".encode())
        self.assertIn("aws_access_key_id", rules(base64.b64encode(once)))

    def test_base64_de_gzip(self):
        compressed = gzip.compress(f"key {AWS_KEY}".encode())
        self.assertIn("aws_access_key_id", rules(base64.b64encode(compressed)))

    def test_gzip_como_archivo_adjunto(self):
        self.assertIn("aws_access_key_id", rules(gzip.compress(f"AWS={AWS_KEY}".encode())))

    def test_percent_encoding(self):
        self.assertIn("aws_access_key_id", rules(f"prompt=llave%20{AWS_KEY}".encode()))

    def test_percent_encoding_en_query_string(self):
        found = rules(b"", query=f"q=revisa%20esta%20llave%20{AWS_KEY}")
        self.assertIn("aws_access_key_id", found)

    def test_utf16_con_bom(self):
        self.assertIn("aws_access_key_id", rules(f"llave {AWS_KEY}".encode("utf-16")))

    def test_utf16_sin_bom(self):
        self.assertIn("aws_access_key_id", rules(f"llave {AWS_KEY}".encode("utf-16-le")))

    def test_escapes_unicode_de_json(self):
        escaped = "".join(f"\\u{ord(char):04x}" for char in ANTHROPIC_KEY)
        body = ('{"messages":[{"content":"' + escaped + '"}]}').encode()
        self.assertIn("anthropic_api_key", rules(body))


class TestContainerEvasion(unittest.TestCase):
    def _docx(self, text: str) -> bytes:
        # Comprimido de verdad, como lo escribe Word. Sin esto el texto queda
        # legible dentro del zip y el test pasa aunque nadie lo haya abierto,
        # que es la peor forma de tener cobertura: la que miente.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", f"<w:t>{text}</w:t>")
        return buffer.getvalue()

    def test_documento_de_word(self):
        self.assertIn("aws_access_key_id", rules(self._docx(f"la llave es {AWS_KEY}")))

    def test_multipart_con_archivo(self):
        body = (
            b"--X\r\n"
            b'Content-Disposition: form-data; name="file"; filename="config.env"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
            + f"AWS_ACCESS_KEY_ID={AWS_KEY}\r\n".encode()
            + b"--X--\r\n"
        )
        self.assertIn("aws_access_key_id", rules(body))

    def _adjunto(self, nombre: str, tipo: str, contenido: bytes) -> bytes:
        return (
            b"--X\r\n"
            + f'Content-Disposition: form-data; name="file"; filename="{nombre}"\r\n'.encode()
            + f"Content-Type: {tipo}\r\n\r\n".encode()
            + contenido
            + b"\r\n--X--\r\n"
        )

    def test_docx_adjuntado_en_un_multipart(self):
        """El gesto real: arrastrar un Word a un chat de IA.

        El .docx no llega como cuerpo entero sino envuelto en un multipart, asi
        que el zip arranca en el medio del payload y no en el primer byte. Mirar
        solo el principio deja pasar el caso mas comun que existe.
        """

        cuerpo = self._adjunto(
            "propuesta.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            self._docx(f"la llave es {AWS_KEY}"),
        )
        self.assertIn("aws_access_key_id", rules(cuerpo))

    def test_gzip_adjuntado_en_un_multipart(self):
        cuerpo = self._adjunto(
            "notas.gz",
            "application/gzip",
            gzip.compress(f"AWS_ACCESS_KEY_ID={AWS_KEY}".encode()),
        )
        self.assertIn("aws_access_key_id", rules(cuerpo))

    def test_zip_corrupto_no_revienta(self):
        self.assertEqual(rules(b"PK\x03\x04basura que no es un zip"), set())


class TestSplittingEvasion(unittest.TestCase):
    def test_secreto_partido_con_espacios(self):
        self.assertIn("aws_access_key_id", rules(b"AKIA IOSFODNN7 EXAMPLE"))

    def test_secreto_partido_con_saltos_de_linea(self):
        self.assertIn("aws_access_key_id", rules(b"AKIAIOSF\nODNN7EXAMPLE"))

    def test_secreto_al_final_de_un_payload_gigante(self):
        relleno = b"texto sin nada interesante. " * 60_000
        body = relleno + f"\nAWS_ACCESS_KEY_ID={AWS_KEY}\n".encode()
        self.assertGreater(len(body), MAX_INSPECT_BYTES)
        result = scan_payload(body)
        self.assertIn("aws_access_key_id", {f.rule_id for f in result.findings})
        self.assertTrue(result.truncated)


class TestNoRompeLoNormal(unittest.TestCase):
    def test_prompt_de_trabajo_no_dispara(self):
        prompt = (
            "Ayudame a escribir el correo para el cliente sobre el retraso del "
            "envio. Tono formal pero calido, maximo tres parrafos."
        ).encode()
        self.assertEqual(rules(prompt), set())

    def test_codigo_sin_credenciales_no_dispara(self):
        code = b"""
        import os
        client = Client(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat(model="gpt-4", messages=messages)
        """
        self.assertEqual(rules(code), set())

    def test_body_vacio_no_revienta(self):
        self.assertEqual(rules(b""), set())

    def test_binario_no_revienta(self):
        self.assertEqual(rules(bytes(range(256)) * 100), set())


class TestInvariantes(unittest.TestCase):
    def test_el_mismo_secreto_en_dos_vistas_es_un_solo_hallazgo(self):
        plain = f"key {AWS_KEY} ".encode()
        both = plain + base64.b64encode(plain)
        findings = scan_payload(both).findings
        aws = [f for f in findings if f.rule_id == "aws_access_key_id"]
        self.assertEqual(len(aws), 1)

    def test_la_evidencia_sigue_redactada_en_las_vistas_derivadas(self):
        payload = base64.b64encode(f"key {AWS_KEY}".encode())
        for finding in scan_payload(payload).findings:
            self.assertNotIn(AWS_KEY, finding.evidence)


if __name__ == "__main__":
    unittest.main()
