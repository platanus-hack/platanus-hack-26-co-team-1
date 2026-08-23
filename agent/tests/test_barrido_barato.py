"""scan_preview: lo barato que se paga en cada POST a un destino sin clasificar.

Es el barrido que decide si un dominio nunca visto merece el escaneo completo
(scan_payload). Tiene que encontrar lo obvio -- regex puro, base64, JSON
escapado -- y tiene que ser barato de verdad: nada de contenedores, nada de
archivos, nada de modelo. Esa cobertura mas cara solo se paga una vez que esto
ya encontro algo.
"""

import unittest

from aegis_agent.detect.payload import scan_payload, scan_preview

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


class TestBarridoBarato(unittest.TestCase):
    def test_encuentra_una_llave_en_texto_plano(self):
        hallazgos = scan_preview(f"AWS_ACCESS_KEY_ID={AWS_KEY}")
        self.assertTrue(any(h.rule_id == "aws_access_key_id" for h in hallazgos))

    def test_un_body_limpio_no_genera_nada(self):
        self.assertEqual(scan_preview('{"customer_id": 42, "total": 19900}'), [])

    def test_texto_vacio_no_revienta(self):
        self.assertEqual(scan_preview(""), [])

    def test_encuentra_la_llave_escapada_dentro_de_un_json(self):
        # Un secreto que viaja dentro de otro JSON (un prompt dentro de un
        # payload) llega con los saltos y las comillas escapados.
        preview = '{"nota": "clave: AWS_ACCESS_KEY_ID=%s\n"}' % AWS_KEY
        hallazgos = scan_preview(preview)
        self.assertTrue(any(h.rule_id == "aws_access_key_id" for h in hallazgos))

    def test_encuentra_la_llave_en_base64(self):
        import base64

        codificado = base64.b64encode(f"AWS_ACCESS_KEY_ID={AWS_KEY}".encode()).decode()
        hallazgos = scan_preview(codificado)
        self.assertTrue(any(h.rule_id == "aws_access_key_id" for h in hallazgos))

    def test_no_abre_un_zip_eso_lo_hace_el_escaneo_completo(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("notas.txt", f"AWS_ACCESS_KEY_ID={AWS_KEY}")
        contenido = buffer.getvalue()

        # El barrido barato, que solo mira texto, no ve nada en un binario zip.
        self.assertEqual(scan_preview(contenido.decode("latin-1")), [])
        # El escaneo completo si abre el contenedor y encuentra la llave.
        hallazgos_completos = scan_payload(contenido).findings
        self.assertTrue(
            any(h.rule_id == "aws_access_key_id" for h in hallazgos_completos)
        )


if __name__ == "__main__":
    unittest.main()
