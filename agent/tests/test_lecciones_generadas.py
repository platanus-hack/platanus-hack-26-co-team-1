"""La leccion la escribe un modelo, sin haber visto nunca el dato.

Esta es la tesis del producto: un bloqueo que no ensena nada solo entrena a la
gente a esquivarlo. Y la restriccion que la hace interesante es el ADR 0003: el
contenido no cruza la frontera, asi que la leccion hay que escribirla con la
descripcion del hallazgo y nada mas.

Casi todo lo que se prueba aca es esa frontera, y no la calidad del texto. Que
el modelo escriba bien no lo puede garantizar un test; que no reciba el dato de
la persona, si. Los tests usan un modelo simulado a proposito: lo que se
verifica es el arnes, no el proveedor.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_backend import lecciones  # noqa: E402


def _evento(**cambios) -> dict:
    base = {
        "event_id": "e1",
        "tenant_id": "acme",
        "actor": {"user_id": "u_8f21", "area": "ingenieria", "role": "employee"},
        "destination": {
            "domain": "chat.deepseek.com",
            "classification": "ai_unapproved",
            "process": "chrome.exe",
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
    }
    base.update(cambios)
    return base


class ModeloSimulado:
    """Guarda el prompt que recibio, que es justo lo que hay que auditar."""

    def __init__(self, respuesta: str | None = None, falla: bool = False):
        self.respuesta = respuesta or json.dumps(
            {"title": "Un titulo", "why": "Un porque", "what_to_do": "Un que hacer"}
        )
        self.falla = falla
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.falla:
            raise RuntimeError("el modelo se cayo")
        return self.respuesta


class TestLaFronteraDeDatos(unittest.TestCase):
    """Lo mas importante del archivo: que el contenido no llegue al modelo."""

    def test_un_campo_que_no_esta_en_la_lista_blanca_no_viaja(self):
        # El prompt se arma desde una lista blanca justamente por esto: el dia
        # que alguien agregue un campo al evento, no puede viajar solo.
        modelo = ModeloSimulado()
        evento = _evento(payload="la contrasena es Verano2026Bogota")
        evento["prompt_original"] = "el texto entero que escribio la persona"

        lecciones.generar({"event": evento}, modelo)

        prompt = modelo.prompts[0]
        self.assertNotIn("Verano2026Bogota", prompt)
        self.assertNotIn("el texto entero", prompt)
        self.assertNotIn("payload", prompt)

    def test_la_url_completa_no_viaja_aunque_venga_en_el_evento(self):
        modelo = ModeloSimulado()
        evento = _evento()
        evento["destination"]["url"] = "https://chat.deepseek.com/c/secreto?q=AKIA123"

        lecciones.generar({"event": evento}, modelo)

        self.assertNotIn("secreto", modelo.prompts[0])
        self.assertNotIn("AKIA123", modelo.prompts[0])

    def test_la_evidencia_se_recorta_aunque_ya_venga_redactada(self):
        modelo = ModeloSimulado()
        evento = _evento()
        evento["detection"]["evidence"] = "A" * 200

        lecciones.generar({"event": evento}, modelo)

        self.assertNotIn("A" * (lecciones.EVIDENCIA_MAX + 1), modelo.prompts[0])

    def test_el_identificador_de_la_persona_no_hace_falta_para_ensenar(self):
        modelo = ModeloSimulado()
        lecciones.generar({"event": _evento()}, modelo)
        self.assertNotIn("u_8f21", modelo.prompts[0])

    def test_lo_que_si_viaja_es_lo_que_describe_el_hallazgo(self):
        # El contrapeso de los tests de arriba: si no viajara nada util, la
        # leccion seria la misma para todo y no habria producto.
        modelo = ModeloSimulado()
        lecciones.generar({"event": _evento()}, modelo)
        prompt = modelo.prompts[0]
        for esperado in ("aws_access_key_id", "secret", "chat.deepseek.com", "ingenieria"):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, prompt)


class TestDegradacion(unittest.TestCase):
    """Sin modelo se ensena menos, pero no se deja de ensenar."""

    def test_sin_modelo_queda_la_leccion_escrita_a_mano(self):
        leccion = lecciones.generar({"event": _evento()}, None)
        self.assertEqual(leccion["generada_por"], "estatica")
        self.assertTrue(leccion["title"])
        self.assertTrue(leccion["what_to_do"])

    def test_si_el_modelo_revienta_queda_la_leccion_escrita_a_mano(self):
        leccion = lecciones.generar({"event": _evento()}, ModeloSimulado(falla=True))
        self.assertEqual(leccion["generada_por"], "estatica")

    def test_si_el_modelo_contesta_cualquier_cosa_queda_el_respaldo(self):
        leccion = lecciones.generar({"event": _evento()}, ModeloSimulado("perdon, no puedo"))
        self.assertEqual(leccion["generada_por"], "estatica")

    def test_una_respuesta_incompleta_no_se_da_por_buena(self):
        # Media leccion es peor que la generica: deja a la persona sin el "que
        # hacer", que es la mitad que le permite seguir trabajando.
        a_medias = json.dumps({"title": "Solo un titulo"})
        leccion = lecciones.generar({"event": _evento()}, ModeloSimulado(a_medias))
        self.assertEqual(leccion["generada_por"], "estatica")

    def test_el_json_envuelto_en_prosa_igual_se_lee(self):
        envuelto = 'Claro, aca va:\n```json\n{"title":"T","why":"P","what_to_do":"Q"}\n```'
        leccion = lecciones.generar({"event": _evento()}, ModeloSimulado(envuelto))
        self.assertEqual(leccion["generada_por"], "modelo")
        self.assertEqual(leccion["title"], "T")


class TestLaCache(unittest.TestCase):
    """Dos personas con el mismo incidente merecen la misma leccion, y una sola llamada."""

    def test_el_mismo_incidente_no_se_le_pide_dos_veces_al_modelo(self):
        modelo = ModeloSimulado()
        cache: dict = {}
        lecciones.generar({"event": _evento()}, modelo, cache)
        segunda = lecciones.generar({"event": _evento(event_id="e2")}, modelo, cache)

        self.assertEqual(len(modelo.prompts), 1)
        self.assertEqual(segunda["generada_por"], "cache")

    def test_la_leccion_cacheada_se_devuelve_con_el_event_id_de_quien_pregunta(self):
        modelo = ModeloSimulado()
        cache: dict = {}
        lecciones.generar({"event": _evento()}, modelo, cache)
        segunda = lecciones.generar({"event": _evento(event_id="otro")}, modelo, cache)
        self.assertEqual(segunda["event_id"], "otro")

    def test_reincidir_cambia_la_leccion(self):
        # A alguien que repite hay que decirle algo distinto, asi que no puede
        # compartir la entrada de cache con quien lo hizo por primera vez.
        modelo = ModeloSimulado()
        cache: dict = {}
        lecciones.generar({"event": _evento()}, modelo, cache)
        lecciones.generar({"event": _evento(), "repeticiones": 5}, modelo, cache)
        self.assertEqual(len(modelo.prompts), 2)

    def test_dos_areas_distintas_reciben_lecciones_distintas(self):
        modelo = ModeloSimulado()
        cache: dict = {}
        otra = _evento()
        otra["actor"] = {"user_id": "u_2", "area": "legal", "role": "employee"}
        lecciones.generar({"event": _evento()}, modelo, cache)
        lecciones.generar({"event": otra}, modelo, cache)
        self.assertEqual(len(modelo.prompts), 2)


class TestElPromptLeDiceQueNoPidaElContenido(unittest.TestCase):
    def test_las_instrucciones_prohiben_pedir_o_inventar_el_texto(self):
        # El modelo no tiene el contenido; sin esto, la mitad de las lecciones
        # empiezan con "no puedo ver lo que escribiste", que no le sirve a nadie.
        modelo = ModeloSimulado()
        lecciones.generar({"event": _evento()}, modelo)
        # Se normalizan los saltos de linea: lo que importa es que la
        # instruccion este, no como quedo cortado el parrafo.
        instrucciones = " ".join(modelo.prompts[0].lower().split())
        self.assertIn("no lo pidas", instrucciones)
        self.assertIn("no lo inventes", instrucciones)


if __name__ == "__main__":
    unittest.main()
