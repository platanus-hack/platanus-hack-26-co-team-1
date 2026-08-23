"""Encontrar el shadow AI que no esta en ninguna lista y no parece nada.

Un catalogo cubre lo conocido. Lo que aparecio el martes se detecta por como se
comporta: responde con streaming, recibe bloques largos de texto libre, o manda
un cuerpo con forma de llamada a un modelo. Estas son las senales, y ninguna
requiere saber como se llama el servicio.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_agent.signals import (  # noqa: E402
    MIN_TEXTO_LARGO,
    PESO_STREAMING,
    UMBRAL,
    SignalCollector,
)
from aegis_backend.classifier import classify, content_score  # noqa: E402
from aegis_backend.evidence import Evidence  # noqa: E402

TEXTO_LARGO = "Necesito que me ayudes con esto. " * 12


class TestSenales(unittest.TestCase):
    def setUp(self):
        self.senales = SignalCollector()

    def test_el_streaming_solo_ya_alcanza(self):
        # Es la huella mas fiable: casi ningun servicio normal responde asi.
        self.senales.observe_response("raro.co", "text/event-stream")
        self.assertGreaterEqual(self.senales.score("raro.co"), UMBRAL)
        self.assertTrue(self.senales.should_classify("raro.co"))

    def test_el_ndjson_tambien_cuenta_como_streaming(self):
        self.senales.observe_response("raro.co", "application/x-ndjson; charset=utf-8")
        self.assertEqual(self.senales.score("raro.co"), PESO_STREAMING)

    def test_forma_mas_texto_largo_tambien_alcanza(self):
        self.senales.observe_request("raro.co", True, TEXTO_LARGO)
        self.assertGreaterEqual(self.senales.score("raro.co"), UMBRAL)

    def test_un_json_normal_no_levanta_sospecha(self):
        self.senales.observe_response("facturacion.co", "application/json")
        self.senales.observe_request("facturacion.co", False, '{"total": 19900}')
        self.assertLess(self.senales.score("facturacion.co"), UMBRAL)
        self.assertFalse(self.senales.should_classify("facturacion.co"))

    def test_un_campo_corto_no_es_una_conversacion(self):
        self.senales.observe_request("tienda.co", False, "a" * (MIN_TEXTO_LARGO - 1))
        self.assertEqual(self.senales.score("tienda.co"), 0)

    def test_solo_se_pide_la_clasificacion_una_vez(self):
        # Sin esto el backend recibiria una tormenta por cada pestana abierta.
        self.senales.observe_response("raro.co", "text/event-stream")
        self.assertTrue(self.senales.should_classify("raro.co"))
        self.assertFalse(self.senales.should_classify("raro.co"))

    def test_guarda_por_que_sospecho(self):
        self.senales.observe_response("raro.co", "text/event-stream")
        self.assertIn("streaming", " ".join(self.senales.reasons("raro.co")))

    def test_un_dato_sensible_hacia_un_destino_desconocido_alcanza_solo(self):
        # Una llave de AWS saliendo hacia un dominio nunca visto es la senal
        # mas fuerte que hay: no necesita nada mas para pedir la clasificacion.
        self.senales.observe_sensitive_egress("desconocido.co")
        self.assertGreaterEqual(self.senales.score("desconocido.co"), UMBRAL)
        self.assertTrue(self.senales.should_classify("desconocido.co"))

    def test_el_motivo_del_dato_sensible_queda_registrado(self):
        self.senales.observe_sensitive_egress("desconocido.co")
        self.assertIn(
            "sali", " ".join(self.senales.reasons("desconocido.co")).lower()
        )

    def test_los_dominios_no_se_mezclan(self):
        self.senales.observe_response("uno.co", "text/event-stream")
        self.assertEqual(self.senales.score("dos.co"), 0)


class TestClasificacionPorContenido(unittest.TestCase):
    """El nombre no alcanza: hay que mirar lo que el sitio dice de si mismo."""

    def _evidencia(self, titulo="", descripcion="", texto=""):
        return Evidence(
            domain="ejemplo.co",
            reachable=True,
            title=titulo,
            description=descripcion,
            snippet=texto,
        )

    def test_un_sitio_que_se_presenta_como_ia_puntua_alto(self):
        puntaje, motivo = content_score(
            self._evidencia(
                titulo="Monica",
                descripcion="Tu asistente de IA para escribir y resumir",
                texto="Chat con IA en cualquier pagina. Powered by GPT.",
            )
        )
        self.assertGreaterEqual(puntaje, 0.6)
        # El motivo tiene que nombrar la senal concreta, porque termina en el
        # panel y un administrador necesita poder discutir el veredicto.
        self.assertIn("El sitio", motivo)
        self.assertNotIn("no se presenta", motivo)

    def test_una_tienda_no_puntua(self):
        puntaje, _ = content_score(
            self._evidencia(
                titulo="Ferreteria El Tornillo",
                descripcion="Herramientas y materiales de construccion",
                texto="Envios a todo el pais. Catalogo de productos.",
            )
        )
        self.assertLess(puntaje, 0.6)

    def test_un_sitio_que_no_responde_no_se_condena_por_el_contenido(self):
        puntaje, motivo = content_score(Evidence(domain="x.co", reachable=False))
        self.assertEqual(puntaje, 0.0)
        self.assertIn("no respondio", motivo)


class TestVeredicto(unittest.TestCase):
    def _falso_fetch(self, **campos):
        def buscar(domain):
            return Evidence(domain=domain, reachable=True, **campos)

        return buscar

    def test_un_nombre_inocente_con_sitio_de_ia_se_detecta(self):
        # El caso que importa: monica.im no dice "IA" por ningun lado.
        veredicto = classify(
            "monica.im",
            buscar_evidencia=self._falso_fetch(
                title="Monica",
                description="Tu asistente de IA para escribir",
                snippet="Chat con IA. Powered by GPT. Pregunta lo que quieras.",
            ),
        )
        self.assertEqual(veredicto.classification, "ai_unapproved")

    def test_un_nombre_con_ia_pero_sitio_normal_no_se_condena_solo(self):
        veredicto = classify(
            "aidacontabilidad.co",
            buscar_evidencia=self._falso_fetch(
                title="Aida Contabilidad",
                description="Servicios contables para pymes",
                snippet="Declaracion de renta, nomina y facturacion electronica.",
            ),
        )
        self.assertEqual(veredicto.classification, "non_ai")

    def test_el_modelo_tiene_la_ultima_palabra(self):
        import json as _json

        def modelo(prompt):
            self.assertIn("herramienta.co", prompt)
            self.assertIn("Texto de la portada", prompt)
            return _json.dumps(
                {
                    "es_ia": True,
                    "tipo": "ai_feature",
                    "confianza": 0.91,
                    "evidencia": "Ofrece resumir documentos con un modelo",
                }
            )

        veredicto = classify(
            "herramienta.co",
            ask_model=modelo,
            buscar_evidencia=self._falso_fetch(
                title="Herramienta",
                description="Productividad para equipos",
                snippet="Sube tu documento y obtene un resumen al instante.",
            ),
        )
        self.assertEqual(veredicto.source, "llm_classifier")
        self.assertEqual(veredicto.classification, "ai_unapproved")
        self.assertEqual(veredicto.kind, "ai_feature")

    def test_si_el_sitio_no_responde_queda_la_heuristica_del_nombre(self):
        def sin_respuesta(domain):
            return Evidence(domain=domain, reachable=False, error="timeout")

        veredicto = classify("chatgpt-libre.co", buscar_evidencia=sin_respuesta)
        self.assertEqual(veredicto.classification, "ai_unapproved")
        self.assertEqual(veredicto.source, "heuristic")


if __name__ == "__main__":
    unittest.main()
