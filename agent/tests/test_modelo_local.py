"""El nivel T2: el modelo local.

Los tests con el modelo de verdad se saltan si no esta instalado, porque el
agente tiene que funcionar sin el. Los de integracion usan un modelo simulado y
corren siempre: lo que se verifica ahi no es que el modelo acierte, sino que
todo lo que lo rodea se comporte bien cuando acierta, cuando falla y cuando no
esta.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aegis_agent.detect import model
from aegis_agent.detect.payload import scan_payload
from aegis_agent.detect.types import Finding
from aegis_agent.policy import Policy
from tests.aislamiento import entorno_aislado

TEXTO = "El cliente Bancolombia esta renegociando el contrato de nomina"


class ModeloSimulado:
    """Un modelo que devuelve lo que se le indique, o revienta si se le pide."""

    def __init__(self, entidades=None, demora=0.0, falla=False):
        self.entidades = entidades or []
        self.demora = demora
        self.falla = falla
        self.llamadas = 0

    def predict_entities(self, texto, etiquetas, threshold=0.0):
        self.llamadas += 1
        if self.falla:
            raise RuntimeError("el modelo se cayo")
        if self.demora:
            import time

            time.sleep(self.demora)
        return self.entidades


def con_modelo(simulado, habilitado=True):
    """Prepara el entorno como si el modelo estuviera cargado."""

    return (
        patch.object(model, "_modelo", simulado),
        patch.object(model, "_cargado", True),
        patch.dict(os.environ, {"AEGIS_T2": "1" if habilitado else "0"}),
    )


class TestApagadoPorDefecto(unittest.TestCase):
    def test_sin_la_variable_no_corre(self):
        with patch.dict(os.environ, {"AEGIS_T2": ""}):
            self.assertFalse(model.habilitado())
            self.assertEqual(model.scan_model(TEXTO), [])

    def test_el_agente_funciona_sin_el_modelo(self):
        # Sin T2 el motor sigue detectando todo lo que T1 sabe detectar.
        with patch.dict(os.environ, {"AEGIS_T2": ""}):
            hallazgos = scan_payload(b"AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE").findings
        self.assertTrue(hallazgos)

    def test_el_estado_se_puede_consultar(self):
        estado = model.estado()
        for clave in ("habilitado", "instalado", "cargado", "umbral", "presupuesto_ms"):
            with self.subTest(clave=clave):
                self.assertIn(clave, estado)


class TestHallazgosDelModelo(unittest.TestCase):
    def _correr(self, simulado):
        parches = con_modelo(simulado)
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        return model.scan_model(TEXTO)

    def test_un_nombre_de_cliente_es_dato_de_la_empresa(self):
        hallazgos = self._correr(
            ModeloSimulado(
                [{"label": "nombre de cliente", "score": 0.91, "start": 11, "end": 23}]
            )
        )
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].category, "internal_data")
        self.assertEqual(hallazgos[0].severity, "high")

    def test_un_dato_personal_suelto_es_pii(self):
        hallazgos = self._correr(
            ModeloSimulado([{"label": "persona", "score": 0.88, "start": 0, "end": 3}])
        )
        self.assertEqual(hallazgos[0].category, "pii")

    def test_la_evidencia_no_lleva_el_texto_detectado(self):
        # Vale la misma regla que para T1: sale el tipo, nunca el dato.
        hallazgos = self._correr(
            ModeloSimulado([{"label": "empresa", "score": 0.9}])
        )
        self.assertNotIn("Bancolombia", hallazgos[0].evidence)
        self.assertLessEqual(len(hallazgos[0].evidence), 32)

    def test_no_repite_la_misma_etiqueta(self):
        hallazgos = self._correr(
            ModeloSimulado(
                [
                    {"label": "persona", "score": 0.9},
                    {"label": "persona", "score": 0.8},
                ]
            )
        )
        self.assertEqual(len(hallazgos), 1)


class TestDegradacion(unittest.TestCase):
    """Lo que pasa cuando el modelo se porta mal, que es lo que mas importa."""

    def _con(self, simulado):
        parches = con_modelo(simulado)
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def test_si_el_modelo_revienta_no_se_cae_el_agente(self):
        self._con(ModeloSimulado(falla=True))
        self.assertEqual(model.scan_model(TEXTO), [])

    def test_si_tarda_demasiado_se_descarta_su_respuesta(self):
        # El presupuesto es duro: un modelo lento no puede frenar a la persona.
        lento = ModeloSimulado(
            [{"label": "persona", "score": 0.99}],
            demora=(model.LATENCIA_MAXIMA_MS + 200) / 1000,
        )
        self._con(lento)
        self.assertEqual(model.scan_model(TEXTO), [])
        self.assertEqual(lento.llamadas, 1)

    def test_texto_vacio_no_lo_llama(self):
        simulado = ModeloSimulado([{"label": "persona", "score": 0.9}])
        self._con(simulado)
        self.assertEqual(model.scan_model("   "), [])
        self.assertEqual(simulado.llamadas, 0)


class TestOrdenDeLaCascada(unittest.TestCase):
    def test_si_t1_encontro_algo_el_modelo_no_corre(self):
        simulado = ModeloSimulado([{"label": "persona", "score": 0.99}])
        parches = con_modelo(simulado)
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

        resultado = scan_payload(b"AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        self.assertTrue(resultado.findings)
        self.assertEqual(simulado.llamadas, 0, "T2 corrio aunque T1 ya habia decidido")

    def test_si_t1_no_vio_nada_el_modelo_si_corre(self):
        simulado = ModeloSimulado(
            [{"label": "empresa", "score": 0.9, "start": 0, "end": 5}]
        )
        parches = con_modelo(simulado)
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

        resultado = scan_payload(TEXTO.encode())
        self.assertEqual(simulado.llamadas, 1)
        self.assertTrue(any(f.rule_id.startswith("modelo:") for f in resultado.findings))


class FakeRequest:
    def __init__(self, host, body):
        self.pretty_host = host
        self.path = "/v1/messages"
        self.method = "POST"
        self._body = body
        self.query = None
        # Sin Sec-Fetch-Dest ni Accept, _is_navigation lo trata como un fetch
        # interno y la respuesta de bloqueo sale en JSON, no en HTML.
        self.headers = {}

    def get_content(self, strict=True):
        return self._body

    @property
    def raw_content(self):
        return self._body


class FakeFlow:
    def __init__(self, request):
        self.request = request
        self.response = None


def _hallazgo(rule_id, category, severity="high"):
    return Finding(
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence=0.9,
        evidence="<x>",
        start=0,
        end=1,
    )


def _correr_inspeccion(policy, finding):
    """Corre el addon completo con un unico hallazgo simulado.

    Se mockea scan_payload en vez de armar el escaneo real porque lo que se
    prueba aca es como el addon decide con lo que el escaneo le devuelve, no el
    escaneo en si mismo (eso ya lo cubre test_detect.py).
    """

    from aegis_agent.proxy.addon import Aegis

    with tempfile.TemporaryDirectory() as workdir:
        cola = Path(workdir) / "eventos.jsonl"
        with entorno_aislado(workdir):
            addon = Aegis()
        addon.policy = policy
        addon.queue = cola
        addon.domains.enabled = False
        flow = FakeFlow(FakeRequest("claude.ai", b"hola"))
        with patch("aegis_agent.proxy.addon.scan_payload") as escaneo:
            escaneo.return_value = type(
                "R", (), {"findings": [finding], "truncated": False, "views": 1}
            )()
            addon.request(flow)
        eventos = []
        if cola.exists():
            eventos = [
                json.loads(linea)
                for linea in cola.read_text(encoding="utf-8").splitlines()
                if linea.strip()
            ]
    return flow, eventos


class TestDegradacionPorCategoria(unittest.TestCase):
    """B3: el modelo bloquea lo grave (secret, internal_data) y advierte lo
    demas (pii), consultando la categoria del hallazgo en vez de degradar todo
    a ciegas. model_action="warn" sigue siendo la salida de emergencia que baja
    absolutamente todo, sin mirar la categoria.
    """

    def test_una_etiqueta_precisa_bloquea(self):
        flow, _ = _correr_inspeccion(
            Policy(), _hallazgo("modelo:nombre_de_cliente", "internal_data")
        )
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.response.headers["X-Aegis-Action"], "block_content")

    def test_una_etiqueta_amplia_solo_advierte_aunque_sea_dato_de_empresa(self):
        """La categoria no alcanza: manda cuanto se equivoca la etiqueta.

        "empresa" y "nombre de cliente" son las dos internal_data, pero medidas
        sobre el corpus la primera marca 6 de 36 frases de trabajo normal y la
        segunda 1. Solo la segunda puede cortarle el envio a alguien.
        """

        flow, eventos = _correr_inspeccion(
            Policy(), _hallazgo("modelo:empresa", "internal_data")
        )
        self.assertIsNone(flow.response)
        self.assertEqual(eventos[-1]["action"], "warned")

    def test_un_dato_personal_del_modelo_solo_advierte(self):
        flow, eventos = _correr_inspeccion(Policy(), _hallazgo("modelo:persona", "pii"))
        self.assertIsNone(flow.response)
        self.assertEqual(eventos[-1]["action"], "warned")

    def test_model_action_warn_baja_todo_sin_mirar_la_etiqueta(self):
        politica = Policy(model_action="warn")
        flow, eventos = _correr_inspeccion(
            politica, _hallazgo("modelo:nombre_de_cliente", "internal_data")
        )
        self.assertIsNone(flow.response)
        self.assertEqual(eventos[-1]["action"], "warned")

    def test_la_empresa_puede_autorizar_otra_etiqueta(self):
        """Es lo que la app web va a editar: que etiqueta tiene autoridad."""

        politica = Policy(model_block_labels=frozenset({"empresa"}))
        flow, _ = _correr_inspeccion(
            politica, _hallazgo("modelo:empresa", "internal_data")
        )
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_un_hallazgo_de_t1_no_se_toca(self):
        # Un rule_id que no empieza con "modelo:" ni siquiera entra al chequeo
        # de degradacion: T1 detecta con certeza y sigue bloqueando igual.
        flow, _ = _correr_inspeccion(Policy(), _hallazgo("t1:aws_key", "secret"))
        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.response.headers["X-Aegis-Action"], "block_content")


class TestMetricasDelModelo(unittest.TestCase):
    """B5: que se note cuando el modelo no opino, en vez de descartarlo en silencio."""

    def setUp(self):
        model.reiniciar_metricas()
        self.addCleanup(model.reiniciar_metricas)

    def _con(self, simulado):
        parches = con_modelo(simulado)
        for p in parches:
            p.start()
            self.addCleanup(p.stop)

    def test_las_invocaciones_y_los_hallazgos_se_cuentan(self):
        simulado = ModeloSimulado(
            [{"label": "empresa", "score": 0.9, "start": 0, "end": 5}]
        )
        self._con(simulado)
        model.scan_model(TEXTO)
        model.scan_model(TEXTO)
        estado = model.estado()
        self.assertEqual(estado["invocaciones"], 2)
        self.assertEqual(estado["hallazgos"], 2)
        self.assertEqual(estado["descartes_por_latencia"], 0)

    def test_un_descarte_por_latencia_queda_registrado(self):
        lento = ModeloSimulado(
            [{"label": "persona", "score": 0.99}],
            demora=(model.LATENCIA_MAXIMA_MS + 200) / 1000,
        )
        self._con(lento)
        model.scan_model(TEXTO)
        estado = model.estado()
        self.assertEqual(estado["invocaciones"], 1)
        self.assertEqual(estado["descartes_por_latencia"], 1)
        # El descarte no cuenta como hallazgo: la respuesta se tiro entera.
        self.assertEqual(estado["hallazgos"], 0)

    def test_el_p95_sale_de_las_latencias_observadas(self):
        simulado = ModeloSimulado([])
        self._con(simulado)
        for _ in range(5):
            model.scan_model(TEXTO)
        estado = model.estado()
        self.assertGreaterEqual(estado["latencia_p95_ms"], 0.0)
        # Un modelo simulado sin demora esta muy lejos del presupuesto duro.
        self.assertLess(estado["latencia_p95_ms"], model.LATENCIA_MAXIMA_MS)

    def test_reiniciar_metricas_vuelve_todo_a_cero(self):
        simulado = ModeloSimulado([{"label": "persona", "score": 0.9}])
        self._con(simulado)
        model.scan_model(TEXTO)
        model.reiniciar_metricas()
        estado = model.estado()
        self.assertEqual(estado["invocaciones"], 0)
        self.assertEqual(estado["hallazgos"], 0)
        self.assertEqual(estado["descartes_por_latencia"], 0)
        self.assertEqual(estado["latencia_p95_ms"], 0.0)


@unittest.skipUnless(model.disponible(), "gliner no esta instalado")
class TestModeloReal(unittest.TestCase):
    """Con el modelo de verdad. Se salta si no esta: T2 nunca es un requisito."""

    def test_carga(self):
        with patch.dict(os.environ, {"AEGIS_T2": "1"}):
            self.assertIsNotNone(model.cargar())

    def test_encuentra_un_nombre_de_persona(self):
        with patch.dict(os.environ, {"AEGIS_T2": "1"}):
            hallazgos = model.scan_model("Ana Maria Gomez vive en Bogota")
        self.assertTrue(hallazgos)

    def test_no_marca_un_texto_de_trabajo_normal(self):
        # El criterio de aceptacion mas duro no es cuanto detecta sino cuanto no.
        with patch.dict(os.environ, {"AEGIS_T2": "1"}):
            hallazgos = model.scan_model(
                "Ayudame a escribir el resumen de la reunion de manana en tres vinetas"
            )
        self.assertEqual(hallazgos, [], f"falso positivo: {[h.rule_id for h in hallazgos]}")


if __name__ == "__main__":
    unittest.main()
