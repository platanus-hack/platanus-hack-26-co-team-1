"""Los insights del panel los escribe un modelo, sin haber visto nunca una persona.

Misma tesis que `test_lecciones_generadas.py`: lo que se prueba aca no es que el
modelo escriba bien -eso no lo puede garantizar un test-, sino el arnes. Y el
arnes de los insights es mas estricto que el de las lecciones: ni siquiera un
seudonimo de usuario puede llegar al prompt, porque un panel pensado para
instalar cultura no puede alimentarse con "quien" reincide.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "agent"))

from aegis_backend import insights  # noqa: E402
from aegis_agent.panel.metrics import compute  # noqa: E402


def _evento(**cambios) -> dict:
    base = {
        "event_id": "e1",
        "tenant_id": "acme",
        "actor": {"user_id": "u_marcos_8f21", "area": "contabilidad", "role": "employee"},
        "destination": {
            "domain": "chat.deepseek.com",
            "classification": "ai_unapproved",
            "process": "browser",
        },
        "detection": {
            "rule_id": "aws_access_key_id",
            "category": "secret",
            "severity": "critical",
            "confidence": 0.99,
            "engine": "t1_rules",
            "evidence": "AKIA****************",
        },
        "action": "blocked",
        "occurred_at": "2026-08-20T09:00:00Z",
    }
    base.update(cambios)
    return base


_RESPUESTA_VALIDA = json.dumps(
    {
        "resumen": "Una semana con actividad concentrada en un area.",
        "insights": [
            {
                "titulo": "Contabilidad concentra los bloqueos criticos",
                "detalle": "La mayoria de los intentos de esta semana salieron de un area.",
                "foco": "contabilidad",
                "tipo": "riesgo",
            }
        ],
        "estrategias": [
            {
                "titulo": "Charla corta sobre la alternativa aprobada",
                "detalle": "Compartir con el area que herramienta si esta aprobada para su trabajo.",
                "publico": "contabilidad",
            }
        ],
    }
)


class ModeloSimulado:
    """Guarda el prompt que recibio, que es justo lo que hay que auditar."""

    def __init__(self, respuesta: str | None = None, falla: bool = False):
        self.respuesta = respuesta if respuesta is not None else _RESPUESTA_VALIDA
        self.falla = falla
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.falla:
            raise RuntimeError("el modelo se cayo")
        return self.respuesta


class TestLaFronteraDeDatos(unittest.TestCase):
    """Lo mas importante del archivo: que ninguna persona llegue al modelo."""

    def test_el_seudonimo_de_la_persona_no_viaja(self):
        modelo = ModeloSimulado()
        metricas = compute([_evento(), _evento(event_id="e2", actor={"user_id": "u_marcos_8f21", "area": "contabilidad"})])

        insights.generar(metricas, modelo)

        self.assertNotIn("u_marcos_8f21", modelo.prompts[0])

    def test_lo_que_si_viaja_es_lo_agregado_por_area_y_regla(self):
        # El contrapeso del test de arriba: si no viajara nada util, el insight
        # seria el mismo sin importar que paso en la semana.
        modelo = ModeloSimulado()
        metricas = compute([_evento()])
        insights.generar(metricas, modelo)
        prompt = modelo.prompts[0]
        for esperado in ("aws_access_key_id", "contabilidad", "chat.deepseek.com"):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, prompt)


class TestDegradacion(unittest.TestCase):
    """Sin modelo se ensena menos, pero el panel nunca se queda sin nada."""

    def test_sin_modelo_queda_el_respaldo_escrito_a_mano(self):
        resultado = insights.generar(compute([_evento()]), None)
        self.assertEqual(resultado["generado_por"], "estatico")
        self.assertTrue(resultado["resumen"])
        self.assertTrue(resultado["insights"])
        self.assertTrue(resultado["estrategias"])

    def test_si_el_modelo_revienta_queda_el_respaldo(self):
        resultado = insights.generar(compute([_evento()]), ModeloSimulado(falla=True))
        self.assertEqual(resultado["generado_por"], "estatico")

    def test_una_respuesta_que_no_es_json_cae_al_respaldo(self):
        resultado = insights.generar(compute([_evento()]), ModeloSimulado("no puedo ayudarte con eso"))
        self.assertEqual(resultado["generado_por"], "estatico")

    def test_una_respuesta_incompleta_no_se_da_por_buena(self):
        a_medias = json.dumps({"resumen": "algo"})
        resultado = insights.generar(compute([_evento()]), ModeloSimulado(a_medias))
        self.assertEqual(resultado["generado_por"], "estatico")

    def test_el_respaldo_no_inventa_riesgo_cuando_no_hubo_actividad(self):
        # Semana en cero: mentir que hay riesgo seria peor que no decir nada.
        resultado = insights.generar(compute([]), None)
        self.assertEqual(resultado, {**insights.RESPALDO_SIN_DATOS, "generado_por": "estatico"})

    def test_el_respaldo_con_actividad_es_distinto_al_de_semana_en_cero(self):
        resultado = insights.generar(compute([_evento()]), None)
        self.assertEqual(resultado, {**insights.RESPALDO_CON_DATOS, "generado_por": "estatico"})

    def test_el_json_envuelto_en_prosa_igual_se_lee(self):
        envuelto = f"Claro, aca va:\n```json\n{_RESPUESTA_VALIDA}\n```"
        resultado = insights.generar(compute([_evento()]), ModeloSimulado(envuelto))
        self.assertEqual(resultado["generado_por"], "modelo")
        self.assertEqual(resultado["insights"][0]["foco"], "contabilidad")


class TestLaCache(unittest.TestCase):
    """La misma foto de metricas no se le paga dos veces al modelo."""

    def test_la_misma_ventana_no_se_pide_dos_veces(self):
        modelo = ModeloSimulado()
        cache: dict = {}
        metricas = compute([_evento()])
        insights.generar(metricas, modelo, cache)
        segunda = insights.generar(metricas, modelo, cache)

        self.assertEqual(len(modelo.prompts), 1)
        self.assertEqual(segunda["generado_por"], "cache")

    def test_una_ventana_distinta_si_se_vuelve_a_pedir(self):
        modelo = ModeloSimulado()
        cache: dict = {}
        insights.generar(compute([_evento()]), modelo, cache)
        insights.generar(compute([_evento(), _evento(event_id="e2")]), modelo, cache)
        self.assertEqual(len(modelo.prompts), 2)


class TestElPromptEsPedagogico(unittest.TestCase):
    """El enfasis que pidio el producto: prevenir formando cultura, no castigar."""

    def test_las_instrucciones_prohiben_senalar_individuos(self):
        modelo = ModeloSimulado()
        insights.generar(compute([_evento()]), modelo)
        instrucciones = " ".join(modelo.prompts[0].lower().split())
        self.assertIn("nunca acuses a una persona", instrucciones)
        self.assertIn("nunca de individuos", instrucciones)

    def test_las_instrucciones_piden_distinguir_riesgo_de_adopcion(self):
        modelo = ModeloSimulado()
        insights.generar(compute([_evento()]), modelo)
        instrucciones = " ".join(modelo.prompts[0].lower().split())
        self.assertIn("riesgoso", instrucciones)
        self.assertIn("adopcion", instrucciones)


if __name__ == "__main__":
    unittest.main()
