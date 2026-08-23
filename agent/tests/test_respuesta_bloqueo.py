"""Como se le avisa al usuario depende de quien pregunta.

Un fetch de una aplicacion de una sola pagina que recibe HTML no muestra nada:
se queda girando para siempre y la persona no se entera de que paso. Detectado
con ChatGPT abierto en el navegador, con el mensaje enviado y el spinner
infinito mientras Aegis bloqueaba las 110 peticiones por detras.
"""

import json
import unittest

from aegis_agent.proxy.addon import _deny, _is_navigation


class FakeRequest:
    def __init__(self, headers):
        self.headers = headers


class FakeFlow:
    def __init__(self, headers):
        self.request = FakeRequest(headers)
        self.response = None


HTML = "<html><body>pagina de bloqueo</body></html>"
MENSAJE = "Aegis bloqueo el envio"


class TestDeteccionDeNavegacion(unittest.TestCase):
    def test_abrir_una_pagina_es_navegacion(self):
        self.assertTrue(_is_navigation(FakeFlow({"Sec-Fetch-Dest": "document"})))

    def test_un_fetch_interno_no_lo_es(self):
        for destino in ("empty", "script", "iframe", "image"):
            with self.subTest(destino=destino):
                self.assertFalse(_is_navigation(FakeFlow({"Sec-Fetch-Dest": destino})))

    def test_sin_sec_fetch_dest_se_mira_el_accept(self):
        self.assertTrue(_is_navigation(FakeFlow({"Accept": "text/html,*/*"})))
        self.assertFalse(_is_navigation(FakeFlow({"Accept": "application/json"})))

    def test_un_cliente_sin_cabeceras_recibe_json(self):
        # Un CLI o un script no sabe que hacer con una pagina HTML.
        self.assertFalse(_is_navigation(FakeFlow({})))


class TestRespuesta(unittest.TestCase):
    def test_al_navegador_se_le_da_la_pagina_con_la_leccion(self):
        flujo = FakeFlow({"Sec-Fetch-Dest": "document"})
        _deny(flujo, HTML, MENSAJE, {"X-Aegis-Action": "block_destination"})
        self.assertEqual(flujo.response.status_code, 403)
        self.assertIn("text/html", flujo.response.headers["Content-Type"])
        self.assertIn("pagina de bloqueo", flujo.response.text)

    def test_a_la_aplicacion_se_le_da_un_error_que_puede_mostrar(self):
        flujo = FakeFlow({"Sec-Fetch-Dest": "empty"})
        _deny(flujo, HTML, MENSAJE, {"X-Aegis-Action": "block_content"})
        self.assertEqual(flujo.response.status_code, 403)
        self.assertIn("application/json", flujo.response.headers["Content-Type"])
        cuerpo = json.loads(flujo.response.text)
        self.assertEqual(cuerpo["error"]["type"], "aegis_blocked")
        self.assertIn(MENSAJE, cuerpo["error"]["message"])

    def test_el_motivo_viaja_siempre_en_la_cabecera(self):
        for destino in ("document", "empty"):
            with self.subTest(destino=destino):
                flujo = FakeFlow({"Sec-Fetch-Dest": destino})
                _deny(flujo, HTML, MENSAJE, {"X-Aegis-Action": "block_destination"})
                self.assertEqual(
                    flujo.response.headers["X-Aegis-Action"], "block_destination"
                )
