"""El nivel T2: el modelo local.

Los tests con el modelo de verdad se saltan si no esta instalado, porque el
agente tiene que funcionar sin el. Los de integracion usan un modelo simulado y
corren siempre: lo que se verifica ahi no es que el modelo acierte, sino que
todo lo que lo rodea se comporte bien cuando acierta, cuando falla y cuando no
esta.
"""

import os
import unittest
from unittest.mock import patch

from aegis_agent.detect import model
from aegis_agent.detect.payload import scan_payload

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
                [{"label": "empresa", "score": 0.91, "start": 11, "end": 23}]
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
