"""La base colaborativa: un dominio se investiga una vez para toda la red.

Es la unica parte compartida del sistema y por eso la mas delicada. Los tests
cubren las tres promesas: que el veredicto se reparta, que lo unico que viaje sea
un nombre de dominio, y que el agente siga protegiendo con el backend caido.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_agent.domains import DomainClient  # noqa: E402
from aegis_backend.app import serve  # noqa: E402
from aegis_backend.classifier import classify, heuristic_score  # noqa: E402
from aegis_backend.store import DomainStore, Verdict  # noqa: E402

TIMEOUT = 6


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until(condition, timeout: float = TIMEOUT) -> bool:
    limite = time.time() + timeout
    ok = False
    while time.time() < limite and not ok:
        ok = condition()
        if not ok:
            time.sleep(0.05)
    return ok


class TestStore(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.path = Path(self.workdir.name) / "dominios.json"

    def _verdict(self, domain="ia-magica.co"):
        return Verdict(
            domain=domain,
            classification="ai_unapproved",
            kind="llm_chat",
            confidence=0.9,
            evidence="Interfaz de chat con un modelo",
            source="heuristic",
            classified_at=time.time(),
        )

    def test_guarda_y_devuelve(self):
        store = DomainStore(self.path)
        store.put(self._verdict())
        self.assertEqual(store.get("ia-magica.co").classification, "ai_unapproved")

    def test_el_veredicto_sobrevive_al_reinicio(self):
        DomainStore(self.path).put(self._verdict())
        self.assertIsNotNone(DomainStore(self.path).get("ia-magica.co"))

    def test_el_dominio_se_normaliza(self):
        store = DomainStore(self.path)
        store.put(self._verdict())
        self.assertIsNotNone(store.get("IA-MAGICA.CO."))


class TestClasificador(unittest.TestCase):
    def test_un_nombre_con_senales_de_ia_puntua_alto(self):
        puntaje, _ = heuristic_score("chat-gpt-libre.com")
        self.assertGreaterEqual(puntaje, 0.6)

    def test_un_nombre_de_negocio_no_puntua(self):
        puntaje, _ = heuristic_score("facturacion-acme.com.co")
        self.assertLess(puntaje, 0.6)

    def test_sin_modelo_usa_la_heuristica(self):
        veredicto = classify("asistente-ia-legal.co")
        self.assertEqual(veredicto.source, "heuristic")

    def test_con_modelo_manda_el_modelo(self):
        def modelo(_prompt: str) -> str:
            return json.dumps(
                {
                    "es_ia": True,
                    "tipo": "llm_chat",
                    "confianza": 0.95,
                    "evidencia": "Chat con modelo propio y subida de archivos",
                }
            )

        # Un dominio que la heuristica jamas marcaria: solo el modelo lo ve.
        veredicto = classify("herramienta-productividad.co", modelo)
        self.assertEqual(veredicto.source, "llm_classifier")
        self.assertEqual(veredicto.classification, "ai_unapproved")

    def test_si_el_modelo_falla_queda_la_heuristica(self):
        def modelo(_prompt: str) -> str:
            raise RuntimeError("la API no responde")

        veredicto = classify("chatbot-ventas.co", modelo)
        self.assertEqual(veredicto.source, "heuristic")
        self.assertEqual(veredicto.classification, "ai_unapproved")

    def test_el_prompt_no_pide_contenido_del_usuario(self):
        capturado = {}

        def modelo(prompt: str) -> str:
            capturado["prompt"] = prompt
            return '{"es_ia": false, "tipo": "non_ai", "confianza": 0.9, "evidencia": "x"}'

        classify("ejemplo.co", modelo)
        self.assertIn("ejemplo.co", capturado["prompt"])
        self.assertIn("No incluyas contenido del usuario", capturado["prompt"])


class BackendVivo(unittest.TestCase):
    """Backend real en un puerto libre, con un modelo simulado."""

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        cls.store = DomainStore(Path(cls.workdir.name) / "dominios.json")
        cls.port = free_port()

        def modelo(prompt: str) -> str:
            es_ia = "resumidor" in prompt or "chat" in prompt
            return json.dumps(
                {
                    "es_ia": es_ia,
                    "tipo": "llm_chat" if es_ia else "non_ai",
                    "confianza": 0.93,
                    "evidencia": "Procesa texto del usuario con un modelo",
                }
            )

        cls.server = serve(cls.store, cls.port, modelo)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.workdir.cleanup()

    def _get(self, ruta: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{ruta}", timeout=5) as r:
            return r.status, json.loads(r.read())

    def _post(self, ruta: str, payload: dict):
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{ruta}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())


class TestBackend(BackendVivo):
    def test_un_dominio_nuevo_responde_pendiente_al_instante(self):
        estado, datos = self._get("/v1/domains/resumidor-mistico.co")
        self.assertEqual(estado, 202)
        self.assertEqual(datos["classification"], "pending")

    def test_y_queda_clasificado_para_la_siguiente_consulta(self):
        self._get("/v1/domains/chat-anonimo.co")
        listo = wait_until(lambda: self.store.get("chat-anonimo.co") is not None)
        self.assertTrue(listo, "el backend no clasifico el dominio")
        estado, datos = self._get("/v1/domains/chat-anonimo.co")
        self.assertEqual(estado, 200)
        self.assertEqual(datos["classification"], "ai_unapproved")
        self.assertEqual(datos["source"], "llm_classifier")

    def test_rechaza_un_evento_que_traiga_contenido(self):
        estado, _ = self._post(
            "/v1/events", {"event_id": "x", "payload": "AKIAIOSFODNN7EXAMPLE"}
        )
        self.assertEqual(estado, 422)

    def test_rechaza_una_evidencia_demasiado_larga(self):
        estado, _ = self._post(
            "/v1/events",
            {"event_id": "x", "detection": {"evidence": "A" * 100}},
        )
        self.assertEqual(estado, 422)

    def test_acepta_un_evento_bien_formado(self):
        estado, _ = self._post(
            "/v1/events",
            {
                "event_id": "ok",
                "destination": {"domain": "claude.ai"},
                "detection": {"evidence": "AKIA****"},
                "action": "blocked",
            },
        )
        self.assertEqual(estado, 202)


class TestClienteDelAgente(BackendVivo):
    def _cliente(self, nombre: str) -> DomainClient:
        ruta = Path(self.workdir.name) / f"cache-{nombre}.json"
        return DomainClient(f"http://127.0.0.1:{self.port}", ruta)

    def test_sin_veredicto_no_hay_respuesta_y_no_se_bloquea_nada(self):
        cliente = self._cliente("vacio")
        self.assertIsNone(cliente.cached("desconocido.co"))

    def test_el_veredicto_llega_en_segundo_plano(self):
        cliente = self._cliente("uno")
        cliente.request_classification("chat-secreto.co")
        listo = wait_until(lambda: cliente.cached("chat-secreto.co") is not None)
        self.assertTrue(listo, "el cliente nunca recibio el veredicto")
        self.assertEqual(cliente.cached("chat-secreto.co"), "ai_unapproved")

    def test_lo_que_aprende_una_empresa_lo_saben_todas(self):
        primera = self._cliente("empresa-a")
        primera.request_classification("chat-compartido.co")
        wait_until(lambda: primera.cached("chat-compartido.co") is not None)

        # Otra empresa, otro cache, cero llamadas al modelo: el veredicto ya
        # estaba en la base y llega directo.
        segunda = self._cliente("empresa-b")
        segunda.request_classification("chat-compartido.co")
        listo = wait_until(lambda: segunda.cached("chat-compartido.co") is not None)
        self.assertTrue(listo)
        self.assertEqual(segunda.cached("chat-compartido.co"), "ai_unapproved")

    def test_el_cache_sobrevive_al_reinicio_del_agente(self):
        ruta = Path(self.workdir.name) / "cache-persistente.json"
        primero = DomainClient(f"http://127.0.0.1:{self.port}", ruta)
        primero.request_classification("chat-persistente.co")
        wait_until(lambda: primero.cached("chat-persistente.co") is not None)

        segundo = DomainClient(f"http://127.0.0.1:{self.port}", ruta)
        self.assertEqual(segundo.cached("chat-persistente.co"), "ai_unapproved")

    def test_solo_viaja_el_nombre_del_dominio(self):
        pedidos = []
        cliente = self._cliente("espiado")
        original = urllib.request.urlopen

        def espia(peticion, *args, **kwargs):
            pedidos.append(peticion.full_url if hasattr(peticion, "full_url") else str(peticion))
            return original(peticion, *args, **kwargs)

        urllib.request.urlopen = espia
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", original))

        cliente.request_classification("chat-observado.co")
        wait_until(lambda: bool(pedidos))
        self.assertTrue(pedidos)
        for url in pedidos:
            self.assertTrue(url.endswith("/v1/domains/chat-observado.co"))


class TestBackendCaido(unittest.TestCase):
    def test_el_agente_sigue_funcionando_sin_backend(self):
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        # Un puerto donde no hay nada escuchando.
        cliente = DomainClient(
            f"http://127.0.0.1:{free_port()}", Path(workdir.name) / "cache.json"
        )
        cliente.request_classification("cualquiera.co")
        time.sleep(0.4)
        self.assertIsNone(cliente.cached("cualquiera.co"))
        self.assertEqual(cliente.known_domains(), [])

    def test_un_cache_corrupto_no_tumba_el_agente(self):
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        ruta = Path(workdir.name) / "cache.json"
        ruta.write_text("{esto no es json", encoding="utf-8")
        cliente = DomainClient("http://127.0.0.1:1", ruta)
        self.assertEqual(cliente.known_domains(), [])


if __name__ == "__main__":
    unittest.main()
