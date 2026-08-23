"""Lo que se le da al modelo local no es lo mismo que se le da a las reglas.

T1 escanea el request entero a proposito. T2 es un extractor de entidades sobre
lenguaje natural, y darle el JSON crudo lo obliga a buscar personas y empresas
entre llaves, comillas y nombres de parametros.
"""

import json
import unittest

from aegis_agent.detect.prompt import extract_prompt


class TestFormasConocidas(unittest.TestCase):
    def test_openai(self):
        cuerpo = json.dumps(
            {
                "model": "gpt-4o",
                "temperature": 0.7,
                "max_tokens": 1024,
                "messages": [
                    {"role": "system", "content": "Sos un asistente util"},
                    {"role": "user", "content": "El cliente Bancolombia renegocia"},
                ],
            }
        )
        extraido = extract_prompt(cuerpo)
        self.assertIn("El cliente Bancolombia renegocia", extraido)
        self.assertNotIn("gpt-4o", extraido)
        self.assertNotIn("max_tokens", extraido)

    def test_anthropic_con_bloques(self):
        cuerpo = json.dumps(
            {
                "model": "claude-opus-4",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Revisa este contrato"},
                            {"type": "image", "source": {"data": "iVBORw0KGgo="}},
                        ],
                    }
                ],
            }
        )
        extraido = extract_prompt(cuerpo)
        self.assertIn("Revisa este contrato", extraido)
        self.assertNotIn("iVBORw0KGgo", extraido)

    def test_gemini(self):
        cuerpo = json.dumps(
            {"contents": [{"parts": [{"text": "Resumi el acuerdo con Ecopetrol"}]}]}
        )
        self.assertIn("Ecopetrol", extract_prompt(cuerpo))

    def test_campo_prompt_suelto(self):
        self.assertIn("hola", extract_prompt(json.dumps({"prompt": "hola"})))
        self.assertIn("hola", extract_prompt(json.dumps({"inputs": "hola"})))


class TestCaidaAlCuerpoCompleto(unittest.TestCase):
    """Devolver vacio es la senal de que hay que mirar todo.

    El shadow AI que todavia no esta en ninguna lista tampoco tiene una forma
    conocida, y ahi recortar el texto seria recortar justo el caso peligroso.
    """

    def test_json_de_forma_desconocida(self):
        self.assertEqual(extract_prompt(json.dumps({"foo": "bar"})), "")

    def test_texto_que_no_es_json(self):
        self.assertEqual(extract_prompt("esto no es json"), "")

    def test_json_roto(self):
        self.assertEqual(extract_prompt('{"messages": [{"content"'), "")


class TestMultipart(unittest.TestCase):
    def test_campo_de_texto(self):
        cuerpo = (
            "--X\r\n"
            'Content-Disposition: form-data; name="prompt"\r\n'
            "\r\n"
            "El paciente Ana Gomez tiene hipertension\r\n"
            "--X--\r\n"
        )
        self.assertIn("hipertension", extract_prompt(cuerpo))

    def test_el_adjunto_no_va_al_modelo(self):
        """Un binario adjunto es trabajo de T1, no del extractor de entidades."""

        cuerpo = (
            "--X\r\n"
            'Content-Disposition: form-data; name="file"; filename="datos.bin"\r\n'
            "\r\n"
            "BASURA BINARIA QUE NO ES LENGUAJE\r\n"
            "--X--\r\n"
        )
        self.assertEqual(extract_prompt(cuerpo), "")


if __name__ == "__main__":
    unittest.main()
