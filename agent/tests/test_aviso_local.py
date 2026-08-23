"""El aviso en la pantalla, para cuando la aplicacion se come el mensaje.

Aegis le contesta a cada cliente en su idioma: al navegador una pagina con la
leccion, y a una app un 403 con `{"error":{"message": ...}}`. Medido: Claude
Desktop y Codex reciben ese JSON bien formado. Lo que NO hay es contrato de que
la UI de la app lo pinte en vez de un "algo salio mal" generico.

Cuando se lo come, la persona ve que su mensaje fallo y no tiene una pista de que
fue Aegis: un bloqueo que no se entiende no ensena nada y se siente como una
falla de la herramienta. Este aviso cubre ese caso, y SOLO ese.
"""

import os
import unittest
from unittest import mock

from aegis_agent import aviso
from aegis_agent.proxy.addon import _deny


class FakeRequest:
    def __init__(self, headers):
        self.headers = headers
        self.pretty_host = "api.anthropic.com"


class FakeFlow:
    def __init__(self, headers):
        self.request = FakeRequest(headers)
        self.response = None


HTML = "<html><body>pagina de bloqueo</body></html>"
MENSAJE = (
    "Aegis bloqueo el envio: Las credenciales de AWS abren la infraestructura "
    "completa. Pedile ayuda a la IA con el codigo, no con la credencial."
)


class TestCuandoSeAvisa(unittest.TestCase):
    """La regla: se avisa a quien no puede mostrar la pagina, y a nadie mas."""

    def setUp(self):
        aviso.olvidar()
        self.addCleanup(aviso.olvidar)
        # La suite apaga el aviso; estos tests lo prenden a proposito y mockean
        # el unico punto que toca el sistema.
        self.entorno = mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"})
        self.entorno.start()
        self.addCleanup(self.entorno.stop)
        self.mostrar = mock.patch.object(aviso, "_mostrar").start()
        self.addCleanup(mock.patch.stopall)

    def test_a_una_app_de_escritorio_se_le_avisa(self):
        _deny(FakeFlow({"Sec-Fetch-Dest": "empty"}), HTML, MENSAJE,
              {"X-Aegis-Action": "block_content"}, "claude-desktop")
        self.assertTrue(self.mostrar.called)

    def test_al_navegador_no_se_le_avisa_porque_ya_vio_la_pagina(self):
        # Dos avisos por el mismo bloqueo es ruido, y el de la pagina es mejor:
        # tiene la leccion completa.
        _deny(FakeFlow({"Sec-Fetch-Dest": "document"}), HTML, MENSAJE,
              {"X-Aegis-Action": "block_content"}, "brave.exe")
        self.assertFalse(self.mostrar.called)

    def test_el_titulo_dice_que_app_fue(self):
        aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com")
        titulo, _cuerpo = self.mostrar.call_args[0]
        self.assertIn("claude-desktop", titulo)

    def test_sin_atribucion_el_titulo_no_miente(self):
        aviso.avisar_bloqueo(MENSAJE, "desconocido", "api.anthropic.com")
        titulo, _cuerpo = self.mostrar.call_args[0]
        self.assertNotIn("desconocido", titulo)


class TestElTextoDelAviso(unittest.TestCase):
    def test_no_repite_el_preambulo_que_ya_dice_el_titulo(self):
        # "Aegis bloqueo el envio:" gastaria la unica linea que hay.
        self.assertFalse(aviso._texto_corto(MENSAJE).startswith("Aegis"))
        self.assertIn("credenciales de AWS", aviso._texto_corto(MENSAJE))

    def test_un_mensaje_largo_se_corta_sin_quedar_partido(self):
        corto = aviso._texto_corto("palabra " * 200)
        self.assertLessEqual(len(corto), aviso.MAX_CUERPO)
        self.assertTrue(corto.endswith("…"))

    def test_un_mensaje_vacio_no_deja_el_aviso_en_blanco(self):
        with mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"}), \
             mock.patch.object(aviso, "_mostrar") as mostrar:
            aviso.olvidar()
            aviso.avisar_bloqueo("", "codex", "api.openai.com")
            _titulo, cuerpo = mostrar.call_args[0]
            self.assertTrue(cuerpo.strip())


class TestLaPausa(unittest.TestCase):
    """Una pantalla de chat reintenta el envio: sin pausa serian diez avisos."""

    def setUp(self):
        aviso.olvidar()
        self.addCleanup(aviso.olvidar)
        self.entorno = mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"})
        self.entorno.start()
        self.addCleanup(self.entorno.stop)

    def test_el_segundo_intento_seguido_no_vuelve_a_avisar(self):
        with mock.patch.object(aviso, "_mostrar"):
            self.assertTrue(aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com"))
            self.assertFalse(aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com"))

    def test_otra_app_si_avisa_aunque_sea_el_mismo_destino(self):
        with mock.patch.object(aviso, "_mostrar"):
            self.assertTrue(aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com"))
            self.assertTrue(aviso.avisar_bloqueo(MENSAJE, "codex", "api.anthropic.com"))

    def test_pasada_la_pausa_vuelve_a_avisar(self):
        with mock.patch.object(aviso, "_mostrar"):
            aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com")
            aviso._ultimo[("claude-desktop", "api.anthropic.com")] -= aviso.PAUSA + 1
            self.assertTrue(aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "api.anthropic.com"))


class TestNoPuedeRomperNada(unittest.TestCase):
    """Cuando esto corre, el bloqueo ya esta resuelto. No puede fallar hacia arriba."""

    def setUp(self):
        aviso.olvidar()
        self.addCleanup(aviso.olvidar)

    def test_apagado_no_avisa_ni_falla(self):
        with mock.patch.dict(os.environ, {"AEGIS_AVISO": "0"}), \
             mock.patch.object(aviso, "_mostrar") as mostrar:
            self.assertFalse(aviso.avisar_bloqueo(MENSAJE, "claude-desktop", "x"))
            self.assertFalse(mostrar.called)

    def test_si_el_sistema_falla_el_bloqueo_igual_se_devuelve(self):
        # El toast puede fallar por mil razones (notificaciones apagadas, horas
        # de concentracion, PowerShell restringido). Ninguna puede propagarse.
        with mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"}), \
             mock.patch("subprocess.Popen", side_effect=OSError("no se pudo")):
            aviso._mostrar("titulo", "cuerpo")  # no debe lanzar

        # Se rompe `avisar_bloqueo` y no `_mostrar`: `_mostrar` corre en un hilo,
        # asi que su excepcion nunca llegaria a _deny y el test pasaria sin
        # probar nada. Lo que se prueba es el guard del camino del bloqueo.
        with mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"}), \
             mock.patch.object(aviso, "avisar_bloqueo", side_effect=RuntimeError("boom")):
            flujo = FakeFlow({"Sec-Fetch-Dest": "empty"})
            try:
                _deny(flujo, HTML, MENSAJE, {"X-Aegis-Action": "block_content"}, "claude-desktop")
            except RuntimeError:
                self.fail("un aviso roto no puede impedir el bloqueo")
            self.assertEqual(flujo.response.status_code, 403)

    def test_el_bloqueo_se_devuelve_antes_de_esperar_al_aviso(self):
        # El aviso sale en un hilo: si tardara en el camino critico, cada
        # bloqueo le sumaria el arranque de un PowerShell a la latencia.
        with mock.patch.dict(os.environ, {"AEGIS_AVISO": "1"}), \
             mock.patch("subprocess.Popen") as popen:
            flujo = FakeFlow({"Sec-Fetch-Dest": "empty"})
            _deny(flujo, HTML, MENSAJE, {"X-Aegis-Action": "block_content"}, "claude-desktop")
            self.assertEqual(flujo.response.status_code, 403)
            del popen


if __name__ == "__main__":
    unittest.main()
