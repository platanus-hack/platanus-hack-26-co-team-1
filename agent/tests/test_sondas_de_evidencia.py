"""Sondas de evidencia: cuando la portada no alcanza, hay otras puertas.

Un SPA vacio no tiene nada legible en "/", y Haiku se queda sin evidencia real
para decidir -- cae a la heuristica del nombre, el veredicto mas fragil que
produce el sistema. Estas rutas publicas suelen delatar a un servicio de IA
incluso cuando la portada no dice nada: un plugin de IA se declara a si mismo,
un manifest nombra la app, un robots.txt lista las rutas que no quiere que
indexen (que suelen ser las de la API), y un openapi.json las documenta.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_backend.classifier import classify  # noqa: E402
from aegis_backend.evidence import UMBRAL_PORTADA_DELGADA, Evidence, fetch  # noqa: E402


def _respuesta(cuerpo: str, status: int = 200):
    class _Ctx:
        def __init__(self, cuerpo, status):
            self.status = status
            self._cuerpo = cuerpo.encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *_args):
            return self._cuerpo

    return _Ctx(cuerpo, status)


def _fallo():
    import urllib.error

    class _Falla:
        def __enter__(self):
            raise urllib.error.URLError("404")

        def __exit__(self, *exc):
            return False

    return _Falla()


class TestFetchDisparaSondas(unittest.TestCase):
    def test_una_portada_completa_no_dispara_sondas(self):
        portada_larga = "<title>Acme</title>" + "<p>Bienvenido a Acme</p>" * 30
        with patch("aegis_backend.evidence.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _respuesta(portada_larga)
            evidencia = fetch("acme.com")

        self.assertGreaterEqual(len(evidencia.snippet), UMBRAL_PORTADA_DELGADA)
        self.assertEqual(evidencia.sondas, "")
        urlopen.assert_called_once()  # solo la portada, ninguna sonda

    def test_una_portada_delgada_sondea_ai_plugin_primero(self):
        respuestas = iter(
            [
                _respuesta("<div id='app'></div>"),  # portada, un SPA vacio
                _respuesta('{"name_for_human": "Asistente Acme"}'),  # ai-plugin.json
            ]
        )
        with patch(
            "aegis_backend.evidence.urllib.request.urlopen",
            side_effect=lambda *a, **k: next(respuestas),
        ) as urlopen:
            evidencia = fetch("spa-vacio.co")

        self.assertIn("ai-plugin", evidencia.sondas.lower())
        # ai-plugin.json es casi definitivo: no hace falta seguir sondeando.
        self.assertEqual(urlopen.call_count, 2)

    def test_sin_ai_plugin_sigue_con_manifest_y_robots(self):
        def _ruta(peticion, *_a, **_k):
            url = peticion.full_url
            if url == "https://spa-vacio.co/":
                resultado = _respuesta("<div id='app'></div>")
            else:
                if url.endswith("manifest.json"):
                    resultado = _respuesta(
                        '{"name": "Chatty", "description": "Habla con un modelo"}'
                    )
                else:
                    if url.endswith("robots.txt"):
                        resultado = _respuesta(
                            "Disallow: /api/chat\nDisallow: /v1/completions\n"
                        )
                    else:
                        resultado = _fallo()  # ai-plugin.json y openapi.json
            return resultado

        with patch(
            "aegis_backend.evidence.urllib.request.urlopen", side_effect=_ruta
        ):
            evidencia = fetch("spa-vacio.co")

        self.assertIn("Chatty", evidencia.sondas)
        self.assertIn("chat", evidencia.sondas.lower())

    def test_ninguna_sonda_responde_deja_las_sondas_vacias(self):
        def _ruta(peticion, *_a, **_k):
            if peticion.full_url == "https://spa-vacio.co/":
                resultado = _respuesta("<div id='app'></div>")
            else:
                resultado = _fallo()
            return resultado

        with patch(
            "aegis_backend.evidence.urllib.request.urlopen", side_effect=_ruta
        ):
            evidencia = fetch("spa-vacio.co")

        self.assertEqual(evidencia.sondas, "")


class TestSondasLleganAlPrompt(unittest.TestCase):
    def test_las_sondas_entran_en_as_text(self):
        evidencia = Evidence(
            domain="spa-vacio.co",
            reachable=True,
            sondas="Publica un ai-plugin.json: se declara como un plugin de IA.",
        )
        self.assertIn("ai-plugin.json", evidencia.as_text())

    def test_las_sondas_llegan_al_prompt_de_haiku(self):
        capturado = {}

        def modelo(prompt):
            capturado["prompt"] = prompt
            return '{"es_ia": true, "tipo": "ai_feature", "confianza": 0.8, "evidencia": "x"}'

        def con_sondas(domain):
            return Evidence(
                domain=domain,
                reachable=True,
                sondas="Publica un ai-plugin.json: se declara como un plugin de IA.",
            )

        classify("spa-vacio.co", ask_model=modelo, buscar_evidencia=con_sondas)
        self.assertIn("ai-plugin.json", capturado["prompt"])


if __name__ == "__main__":
    unittest.main()
