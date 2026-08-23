"""La politica manda sobre el detector: reglas apagadas, terminos y regex propias.

Hasta ahora las 27 reglas T1 eran un tuple fijo: la empresa podia elegir la
accion pero no QUE se detecta. Estos tests fijan el compilador de ruleset
(detect/ruleset.py): a partir de la politica se arma el conjunto de reglas
activas -- las de fabrica menos las apagadas, mas los terminos prohibidos y
las regex de la empresa -- y ese conjunto es lo que recorre el motor.
"""

from __future__ import annotations

import base64
import unittest
from unittest.mock import patch

from aegis_agent.detect import payload as payload_mod
from aegis_agent.detect.engine import scan
from aegis_agent.detect.payload import scan_payload, scan_preview
from aegis_agent.detect.rules import RULES
from aegis_agent.detect.ruleset import RULESET_POR_DEFECTO, RuleSet, ruleset_de
from aegis_agent.policy import CustomRule, Policy

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


class TestRulesetPorDefecto(unittest.TestCase):
    def test_sin_politica_el_motor_se_comporta_como_siempre(self):
        # El default reproduce el comportamiento historico: mismas reglas,
        # mismos hallazgos. Si esto se rompe, cambio el producto sin querer.
        texto = f"la llave es {AWS_KEY}"
        self.assertEqual(
            [f.rule_id for f in scan(texto)],
            [f.rule_id for f in scan(texto, RULESET_POR_DEFECTO.rules)],
        )
        self.assertEqual(RULESET_POR_DEFECTO.rules, RULES)

    def test_una_politica_default_compila_al_mismo_conjunto(self):
        conjunto = ruleset_de(Policy())
        self.assertEqual(conjunto.rules, RULES)
        self.assertEqual(conjunto.disabled, frozenset())


class TestReglasApagadas(unittest.TestCase):
    def test_una_regla_apagada_desaparece_del_conjunto(self):
        conjunto = ruleset_de(Policy(disabled_rules=frozenset({"email_address"})))
        self.assertNotIn("email_address", [r.id for r in conjunto.rules])

    def test_y_el_motor_deja_de_encontrarla(self):
        conjunto = ruleset_de(Policy(disabled_rules=frozenset({"aws_access_key_id"})))
        hallazgos = scan(f"la llave es {AWS_KEY}", conjunto.rules)
        self.assertNotIn("aws_access_key_id", [f.rule_id for f in hallazgos])

    def test_las_demas_reglas_siguen_vivas(self):
        conjunto = ruleset_de(Policy(disabled_rules=frozenset({"email_address"})))
        hallazgos = scan(f"la llave es {AWS_KEY}", conjunto.rules)
        self.assertIn("aws_access_key_id", [f.rule_id for f in hallazgos])


class TestTerminosProhibidos(unittest.TestCase):
    def _conjunto(self, *terminos, categoria="internal_data"):
        return ruleset_de(
            Policy(forbidden_terms=terminos, forbidden_terms_category=categoria)
        )

    def test_un_termino_prohibido_se_encuentra_sin_importar_mayusculas(self):
        conjunto = self._conjunto("proyecto orion")
        hallazgos = scan("avances del Proyecto ORION para el q3", conjunto.rules)
        self.assertIn("termino_prohibido", [f.rule_id for f in hallazgos])

    def test_no_matchea_dentro_de_otra_palabra(self):
        # "SOL" no puede disparar con "solucion": el termino corto de una
        # empresa no puede convertir el espanol entero en un incidente.
        conjunto = self._conjunto("sol")
        self.assertEqual(scan("la solucion del parasol", conjunto.rules), [])

    def test_la_evidencia_no_repite_el_termino(self):
        # El termino ES el secreto: si la evidencia lo repite, el evento que
        # sube al panel se lleva justo lo que no podia salir.
        conjunto = self._conjunto("proyecto orion")
        hallazgos = scan("estado de proyecto orion", conjunto.rules)
        self.assertNotIn("orion", hallazgos[0].evidence.lower())

    def test_la_categoria_es_la_que_pide_la_politica(self):
        conjunto = self._conjunto("cliente estrella", categoria="secret")
        hallazgos = scan("datos de cliente estrella", conjunto.rules)
        self.assertEqual(hallazgos[0].category, "secret")

    def test_sin_terminos_no_se_agrega_la_regla(self):
        conjunto = ruleset_de(Policy())
        self.assertNotIn("termino_prohibido", [r.id for r in conjunto.rules])

    def test_el_termino_prohibido_tambien_se_puede_apagar_por_id(self):
        conjunto = ruleset_de(
            Policy(
                forbidden_terms=("proyecto orion",),
                disabled_rules=frozenset({"termino_prohibido"}),
            )
        )
        self.assertNotIn("termino_prohibido", [r.id for r in conjunto.rules])


class TestReglasPersonalizadas(unittest.TestCase):
    def test_una_regex_de_la_empresa_compila_y_matchea(self):
        conjunto = ruleset_de(
            Policy(custom_rules=(CustomRule(id="ticket_interno", pattern=r"TKT-\d{6}"),))
        )
        hallazgos = scan("mira el TKT-123456 por favor", conjunto.rules)
        self.assertIn("ticket_interno", [f.rule_id for f in hallazgos])

    def test_una_regex_invalida_se_descarta_sin_lanzar(self):
        conjunto = ruleset_de(
            Policy(custom_rules=(CustomRule(id="rota", pattern=r"[sin cerrar"),))
        )
        self.assertIn("rota", conjunto.descartadas)
        self.assertNotIn("rota", [r.id for r in conjunto.rules])

    def test_una_regla_valida_sobrevive_junto_a_una_rota(self):
        conjunto = ruleset_de(
            Policy(
                custom_rules=(
                    CustomRule(id="rota", pattern=r"[sin cerrar"),
                    CustomRule(id="viva", pattern=r"CONF-\d+"),
                )
            )
        )
        self.assertIn("viva", [r.id for r in conjunto.rules])

    def test_una_regla_personalizada_tambien_se_puede_apagar(self):
        conjunto = ruleset_de(
            Policy(
                custom_rules=(CustomRule(id="ticket_interno", pattern=r"TKT-\d+"),),
                disabled_rules=frozenset({"ticket_interno"}),
            )
        )
        self.assertNotIn("ticket_interno", [r.id for r in conjunto.rules])


class TestCachePorIdentidad(unittest.TestCase):
    """Compilar regexes en cada request seria pagar el costo N veces por nada.

    El addon tiene una sola referencia de politica que solo cambia con el
    hot-reload: mientras sea el mismo objeto, el ruleset compilado se reusa.
    """

    def test_la_misma_politica_devuelve_el_mismo_objeto(self):
        politica = Policy(forbidden_terms=("proyecto orion",))
        self.assertIs(ruleset_de(politica), ruleset_de(politica))

    def test_un_swap_de_politica_recompila(self):
        primera = Policy(forbidden_terms=("proyecto orion",))
        segunda = Policy(forbidden_terms=("otro secreto",))
        conjunto_nuevo = (ruleset_de(primera), ruleset_de(segunda))[1]
        self.assertIn(
            "termino_prohibido", [r.id for r in conjunto_nuevo.rules]
        )
        hallazgos = scan("es otro secreto grande", conjunto_nuevo.rules)
        self.assertTrue(hallazgos)


class TestModeloEnElRuleset(unittest.TestCase):
    def test_las_perillas_del_modelo_viajan_en_el_conjunto(self):
        politica = Policy(model_labels=("nombre de cliente",), model_threshold=0.8)
        conjunto = ruleset_de(politica)
        self.assertEqual(conjunto.model_labels, ("nombre de cliente",))
        self.assertEqual(conjunto.model_threshold, 0.8)


class TestPayloadRespetaLaPolitica(unittest.TestCase):
    """scan_payload y scan_preview con un ruleset: la politica alcanza a las
    vistas derivadas y a los hallazgos sinteticos, no solo al texto plano.

    Apagar una regla que igual se encuentra en la vista base64, o un
    bulk_pii_export que ignora disabled_rules, seria una politica que la web
    muestra como apagada y el motor aplica igual.
    """

    def _conjunto(self, **overrides):
        return ruleset_de(Policy(**overrides))

    def test_una_regla_apagada_no_aparece_ni_en_base64(self):
        correo_b64 = base64.b64encode(b"contacto: ana@empresa.com espero respuesta").decode()
        conjunto = self._conjunto(disabled_rules=frozenset({"email_address"}))
        resultado = scan_payload(f'{{"adjunto": "{correo_b64}"}}'.encode(), ruleset=conjunto)
        self.assertNotIn("email_address", [f.rule_id for f in resultado.findings])

    def test_un_termino_prohibido_se_ve_dentro_del_json_escapado(self):
        conjunto = self._conjunto(forbidden_terms=("proyecto orion",))
        cuerpo = b'{"prompt": "resumen del \\u0070royecto orion"}'
        resultado = scan_payload(cuerpo, ruleset=conjunto)
        self.assertIn("termino_prohibido", [f.rule_id for f in resultado.findings])

    def test_bulk_pii_apagado_no_aparece_aunque_haya_quince_correos(self):
        correos = " ".join(f"persona{i}@empresa.com" for i in range(20)).encode()
        conjunto = self._conjunto(disabled_rules=frozenset({"bulk_pii_export"}))
        resultado = scan_payload(correos, ruleset=conjunto)
        self.assertNotIn("bulk_pii_export", [f.rule_id for f in resultado.findings])

    def test_archivo_critico_apagado_no_aparece(self):
        cuerpo = (
            b'Content-Disposition: form-data; name="file"; filename=".env"\r\n'
            b"\r\nDATO=valor\r\n"
        )
        conjunto = self._conjunto(disabled_rules=frozenset({"archivo_critico"}))
        resultado = scan_payload(cuerpo, ruleset=conjunto)
        self.assertNotIn("archivo_critico", [f.rule_id for f in resultado.findings])

    def test_scan_preview_tambien_respeta_las_reglas_apagadas(self):
        conjunto = self._conjunto(disabled_rules=frozenset({"aws_access_key_id"}))
        hallazgos = scan_preview(f"la llave es {AWS_KEY}", ruleset=conjunto)
        self.assertNotIn("aws_access_key_id", [f.rule_id for f in hallazgos])

    def test_scan_preview_encuentra_el_termino_prohibido(self):
        conjunto = self._conjunto(forbidden_terms=("cliente estrella",))
        hallazgos = scan_preview("datos de cliente estrella", ruleset=conjunto)
        self.assertIn("termino_prohibido", [f.rule_id for f in hallazgos])


class TestModeloRecibeLaPolitica(unittest.TestCase):
    """Las perillas del modelo por fin llegan a scan_model.

    model_labels y model_threshold se serializaban y viajaban del backend al
    disco, pero scan_model() se llamaba sin argumentos: eran perillas
    dibujadas. Este test fija que lo que la web configura es lo que corre.
    """

    def test_scan_model_recibe_labels_y_umbral_del_ruleset(self):
        capturado = {}

        def falso_scan_model(texto, etiquetas, umbral):
            capturado["etiquetas"] = etiquetas
            capturado["umbral"] = umbral
            return []

        conjunto = ruleset_de(
            Policy(model_labels=("nombre de cliente",), model_threshold=0.8)
        )
        with patch.object(payload_mod, "scan_model", falso_scan_model):
            scan_payload(b"texto plano sin hallazgos", ruleset=conjunto)

        self.assertEqual(capturado["etiquetas"], ("nombre de cliente",))
        self.assertEqual(capturado["umbral"], 0.8)

    def test_sin_ruleset_scan_model_corre_con_los_defaults(self):
        capturado = {}

        def falso_scan_model(texto, etiquetas, umbral):
            capturado["etiquetas"] = etiquetas
            capturado["umbral"] = umbral
            return []

        with patch.object(payload_mod, "scan_model", falso_scan_model):
            scan_payload(b"texto plano sin hallazgos")

        self.assertEqual(capturado["etiquetas"], RULESET_POR_DEFECTO.model_labels)
        self.assertEqual(capturado["umbral"], RULESET_POR_DEFECTO.model_threshold)


class FakeWebsocketMessage:
    def __init__(self, content: bytes):
        self.content = content
        self.from_client = True


class FakeWebsocket:
    def __init__(self, content: bytes):
        self.messages = [FakeWebsocketMessage(content)]


class TestAddonConLaPolitica(unittest.TestCase):
    """La politica gobierna el request de punta a punta, no solo el motor.

    Estos tests recorren el camino real del addon: un POST hacia una IA
    aprobada con un termino prohibido tiene que salir con 403 y la regla en la
    cabecera, y una regla apagada tiene que dejar pasar lo que ayer bloqueaba.
    """

    def setUp(self):
        import tempfile
        from pathlib import Path

        from tests.test_destino_desconocido import make_addon

        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"
        self._make_addon = make_addon

    def _post(self, addon, body: bytes, host="claude.ai"):
        from tests.test_destino_desconocido import FakeFlow, FakeRequest

        flow = FakeFlow(FakeRequest(host, "/api/enviar", body))
        addon.request(flow)
        return flow

    def test_un_termino_prohibido_corta_el_envio_con_la_regla_en_la_cabecera(self):
        addon = self._make_addon(self.queue, forbidden_terms=("proyecto orion",))
        flow = self._post(addon, b'{"prompt": "avances del proyecto orion"}')

        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.response.headers["X-Aegis-Rule"], "termino_prohibido")

    def test_con_categoria_que_no_bloquea_el_termino_solo_advierte(self):
        addon = self._make_addon(
            self.queue,
            forbidden_terms=("proyecto orion",),
            forbidden_terms_category="pii",
        )
        flow = self._post(addon, b'{"prompt": "avances del proyecto orion"}')

        self.assertIsNone(flow.response)
        self.assertIn("warned", self.queue.read_text(encoding="utf-8"))

    def test_una_regla_de_la_empresa_corta_y_la_pagina_de_bloqueo_no_lanza(self):
        # El rule_id es nuevo: no tiene leccion propia. lesson_for tiene un
        # default justamente para esto; si alguien lo quita, este test avisa.
        addon = self._make_addon(
            self.queue,
            custom_rules=(CustomRule(id="ticket_interno", pattern=r"TKT-\d{6}"),),
        )
        flow = self._post(addon, b'{"prompt": "mira el TKT-123456"}')

        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.response.headers["X-Aegis-Rule"], "ticket_interno")

    def test_una_regla_apagada_deja_pasar_lo_que_ayer_bloqueaba(self):
        addon = self._make_addon(
            self.queue, disabled_rules=frozenset({"aws_access_key_id"})
        )
        flow = self._post(addon, f'{{"nota": "{AWS_KEY}"}}'.encode())

        self.assertIsNone(flow.response)

    def test_el_websocket_redacta_el_termino_prohibido(self):
        from tests.test_destino_desconocido import FakeFlow, FakeRequest

        addon = self._make_addon(self.queue, forbidden_terms=("proyecto orion",))
        flow = FakeFlow(FakeRequest("claude.ai", "/ws", b""))
        flow.websocket = FakeWebsocket(b"te cuento del proyecto orion")

        addon.websocket_message(flow)

        mensaje = flow.websocket.messages[-1].content.decode("utf-8")
        self.assertNotIn("orion", mensaje)
        self.assertIn("Aegis", mensaje)


if __name__ == "__main__":
    unittest.main()
