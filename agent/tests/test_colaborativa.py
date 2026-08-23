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

from aegis_agent import policy_store  # noqa: E402
from aegis_agent.domains import DomainClient  # noqa: E402
from aegis_agent.policy import Policy  # noqa: E402
from aegis_backend.app import serve  # noqa: E402
from aegis_backend.classifier import classify, heuristic_score  # noqa: E402
from aegis_backend.evidence import Evidence  # noqa: E402
from aegis_backend.store import DomainStore, PolicyStore, Verdict, ttl_for, vencido  # noqa: E402

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

    def test_desde_devuelve_solo_lo_clasificado_despues_de_la_marca(self):
        import time as _t

        store = DomainStore(self.path)
        store.put(self._verdict("viejo.co"))
        marca = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_t.time() + 1))
        _t.sleep(1.1)
        store.put(self._verdict("nuevo.co"))

        dominios = {v.domain for v in store.desde(marca)}
        self.assertEqual(dominios, {"nuevo.co"})


class TestTTL(unittest.TestCase):
    """Cuanto dura un veredicto antes de que convenga volver a mirarlo.

    DEFAULT_TTL estaba declarado y nadie lo leia: un veredicto quedaba
    permanente, y un dominio non_ai que lanza su asistente meses despues
    seguia permitido para siempre. El TTL real depende de que tan solido fue
    el veredicto, no de un numero fijo.
    """

    def _verdict(self, source, confidence, hace):
        return Verdict(
            domain="x.co",
            classification="non_ai",
            kind="non_ai",
            confidence=confidence,
            evidence="x",
            source=source,
            classified_at=time.time() - hace,
        )

    def test_confianza_alta_del_modelo_dura_treinta_dias(self):
        veredicto = self._verdict("llm_classifier", 0.95, hace=0)
        self.assertEqual(ttl_for(veredicto), 30 * 24 * 3600)

    def test_heuristica_es_el_veredicto_mas_fragil(self):
        veredicto = self._verdict("heuristic", 0.9, hace=0)
        self.assertLessEqual(ttl_for(veredicto), 48 * 3600)

    def test_confianza_pegada_al_umbral_tambien_es_fragil(self):
        # El modelo dijo que si, pero apenas: no es mas confiable que la
        # heuristica del nombre.
        veredicto = self._verdict("llm_classifier", 0.61, hace=0)
        self.assertLessEqual(ttl_for(veredicto), 48 * 3600)

    def test_manual_review_no_vence_nunca(self):
        veredicto = self._verdict("manual_review", 1.0, hace=365 * 24 * 3600)
        self.assertIsNone(ttl_for(veredicto))
        self.assertFalse(vencido(veredicto, time.time()))

    def test_un_veredicto_fragil_viejo_esta_vencido(self):
        veredicto = self._verdict("heuristic", 0.9, hace=49 * 3600)
        self.assertTrue(vencido(veredicto, time.time()))

    def test_un_veredicto_fragil_reciente_no_esta_vencido(self):
        veredicto = self._verdict("heuristic", 0.9, hace=1)
        self.assertFalse(vencido(veredicto, time.time()))


class TestCacheDeSubdominios(unittest.TestCase):
    """El cache local del cliente hereda por sufijo, igual que policy.classify.

    Sin esto, un veredicto sobre acme.com no cubre chat.acme.com: cada
    subdominio nuevo del mismo shadow AI se investigaria de cero.
    """

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.cache_path = Path(self.workdir.name) / "cache.json"
        self.cache_path.write_text(
            json.dumps(
                {
                    "acme.com": {
                        "classification": "ai_unapproved",
                        "kind": "llm_chat",
                        "confidence": 0.9,
                        "evidence": "Asistente interno",
                        "source": "heuristic",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.cliente = DomainClient(cache_path=self.cache_path, enabled=False)

    def test_un_subdominio_hereda_el_veredicto_del_padre(self):
        self.assertEqual(self.cliente.cached("chat.acme.com"), "ai_unapproved")

    def test_un_dominio_no_relacionado_no_matchea(self):
        self.assertIsNone(self.cliente.cached("otraempresa.co"))


def sin_sitio(domain):
    """Fetcher falso: los tests no salen a internet.

    Un test que depende de que un dominio exista falla el dia que alguien lo
    registra, y en la mitad de una demo.
    """

    return Evidence(domain=domain, reachable=False, error="sin red en los tests")


class TestClasificador(unittest.TestCase):
    def test_un_nombre_con_senales_de_ia_puntua_alto(self):
        puntaje, _ = heuristic_score("chat-gpt-libre.com")
        self.assertGreaterEqual(puntaje, 0.6)

    def test_un_nombre_de_negocio_no_puntua(self):
        puntaje, _ = heuristic_score("facturacion-acme.com.co")
        self.assertLess(puntaje, 0.6)

    def test_sin_modelo_usa_la_heuristica(self):
        veredicto = classify("asistente-ia-legal.co", buscar_evidencia=sin_sitio)
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
        veredicto = classify("herramienta-productividad.co", modelo, sin_sitio)
        self.assertEqual(veredicto.source, "llm_classifier")
        self.assertEqual(veredicto.classification, "ai_unapproved")

    def test_si_el_modelo_falla_queda_la_heuristica(self):
        def modelo(_prompt: str) -> str:
            raise RuntimeError("la API no responde")

        veredicto = classify("chatbot-ventas.co", modelo, sin_sitio)
        self.assertEqual(veredicto.source, "heuristic")
        self.assertEqual(veredicto.classification, "ai_unapproved")

    def test_el_prompt_no_pide_contenido_del_usuario(self):
        capturado = {}

        def modelo(prompt: str) -> str:
            capturado["prompt"] = prompt
            return '{"es_ia": false, "tipo": "non_ai", "confianza": 0.9, "evidencia": "x"}'

        classify("ejemplo.co", modelo, sin_sitio)
        self.assertIn("ejemplo.co", capturado["prompt"])
        self.assertIn("No incluyas contenido del usuario", capturado["prompt"])


class BackendVivo(unittest.TestCase):
    """Backend real en un puerto libre, con un modelo simulado."""

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory()
        cls.store = DomainStore(Path(cls.workdir.name) / "dominios.json")
        cls.policy_store = PolicyStore(Path(cls.workdir.name) / "politicas.json")
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

        cls.server = serve(cls.store, cls.port, modelo, cls.policy_store)
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

    def _put(self, ruta: str, payload: dict):
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{ruta}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
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


class TestReclasificacionPorTTL(BackendVivo):
    """Un veredicto vencido no deja al agente sin respuesta.

    Se activa por demanda, sin cron: el GET que lo pide de vuelta se lleva el
    veredicto viejo al instante (mejor una respuesta vieja que ninguna) y
    dispara la reclasificacion en segundo plano, igual que un dominio nuevo.
    """

    def test_un_veredicto_vencido_se_devuelve_igual_y_se_reencola(self):
        viejo = Verdict(
            domain="viejo-heuristico.co",
            classification="non_ai",
            kind="non_ai",
            confidence=0.3,
            evidence="El nombre no da senales de un servicio de IA",
            source="heuristic",
            classified_at=time.time() - (49 * 3600),  # el TTL fragil es 48h
        )
        self.store.put(viejo)

        estado, datos = self._get("/v1/domains/viejo-heuristico.co")

        self.assertEqual(estado, 200)
        self.assertEqual(datos["classification"], "non_ai")

        listo = wait_until(
            lambda: self.store.get("viejo-heuristico.co").classified_at
            > viejo.classified_at
        )
        self.assertTrue(listo, "el dominio vencido no se reencolo")

    def test_un_veredicto_vigente_no_se_reclasifica(self):
        vigente = Verdict(
            domain="fresco.co",
            classification="non_ai",
            kind="non_ai",
            confidence=0.9,
            evidence="x",
            source="llm_classifier",
            classified_at=time.time(),
        )
        self.store.put(vigente)

        self._get("/v1/domains/fresco.co")
        time.sleep(0.3)

        self.assertEqual(
            self.store.get("fresco.co").classified_at, vigente.classified_at
        )

    def test_manual_review_nunca_se_reclasifica(self):
        revisado = Verdict(
            domain="revisado-a-mano.co",
            classification="ai_unapproved",
            kind="llm_chat",
            confidence=1.0,
            evidence="Revisado por el equipo de seguridad",
            source="manual_review",
            classified_at=time.time() - (365 * 24 * 3600),
        )
        self.store.put(revisado)

        estado, _ = self._get("/v1/domains/revisado-a-mano.co")
        time.sleep(0.3)

        self.assertEqual(estado, 200)
        self.assertEqual(
            self.store.get("revisado-a-mano.co").classified_at,
            revisado.classified_at,
        )


class TestSincronizacion(BackendVivo):
    """GET /v1/domains/sync: el delta que el agente baja para su cache local.

    Existe para que la lista negra sea instantanea en el camino critico (ver
    suffixes.py): el agente no consulta la base en cada request, la
    sincroniza de vez en cuando y compara en memoria.
    """

    def test_devuelve_solo_lo_actualizado_desde_la_marca(self):
        self.store.put(
            Verdict(
                domain="viejo-sync.co",
                classification="non_ai",
                kind="non_ai",
                confidence=0.2,
                evidence="x",
                source="heuristic",
                classified_at=time.time() - (10 * 24 * 3600),
            )
        )
        marca = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))

        estado, datos = self._get(f"/v1/domains/sync?desde={marca}")

        self.assertEqual(estado, 200)
        dominios = {v["domain"] for v in datos["dominios"]}
        self.assertNotIn("viejo-sync.co", dominios)
        self.assertIn("hasta", datos)

    def test_un_dominio_reciente_si_aparece(self):
        self.store.put(
            Verdict(
                domain="fresco-sync.co",
                classification="ai_unapproved",
                kind="llm_chat",
                confidence=0.9,
                evidence="x",
                source="llm_classifier",
                classified_at=time.time(),
            )
        )
        marca = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))

        estado, datos = self._get(f"/v1/domains/sync?desde={marca}")

        dominios = {v["domain"] for v in datos["dominios"]}
        self.assertIn("fresco-sync.co", dominios)

    def test_sync_no_se_confunde_con_un_dominio_llamado_sync(self):
        # La ruta /v1/domains/ es un prefijo generico; /sync no puede caer
        # ahi como si "sync" fuera el nombre de un dominio a clasificar.
        estado, datos = self._get("/v1/domains/sync?desde=1970-01-01T00:00:00Z")
        self.assertEqual(estado, 200)
        self.assertIn("dominios", datos)


class TestSincronizacionDelAgente(BackendVivo):
    """DomainClient.sincronizar(): el agente baja el delta y lo mezcla local.

    Es lo que hace que la lista negra sea instantanea (suffixes.py) sin dejar
    de estar al dia: se sincroniza de vez en cuando, no en cada request.
    """

    def _cliente(self):
        ruta = Path(self.workdir.name) / f"cache-{id(self)}.json"
        return DomainClient(f"http://127.0.0.1:{self.port}", ruta)

    def test_sincronizar_trae_lo_que_ya_esta_clasificado(self):
        self.store.put(
            Verdict(
                domain="ya-clasificado.co",
                classification="ai_unapproved",
                kind="llm_chat",
                confidence=0.9,
                evidence="x",
                source="llm_classifier",
                classified_at=time.time(),
            )
        )
        cliente = self._cliente()

        cliente.sincronizar()

        self.assertEqual(cliente.cached("ya-clasificado.co"), "ai_unapproved")

    def test_sincronizar_dos_veces_no_vuelve_a_traer_lo_viejo(self):
        cliente = self._cliente()
        cliente.sincronizar()  # deja la marca en "ahora"

        self.store.put(
            Verdict(
                domain="viejo-antes-de-sincronizar.co",
                classification="non_ai",
                kind="non_ai",
                confidence=0.1,
                evidence="x",
                source="heuristic",
                classified_at=time.time() - (10 * 24 * 3600),
            )
        )
        cliente.sincronizar()

        self.assertIsNone(cliente.cached("viejo-antes-de-sincronizar.co"))

    def test_sin_backend_no_lanza_y_el_cache_queda_como_estaba(self):
        ruta = Path(self.workdir.name) / "cache-sin-backend.json"
        cliente = DomainClient("http://127.0.0.1:1", ruta)

        cliente.sincronizar()  # no debe lanzar

        self.assertIsNone(cliente.cached("cualquiera.co"))


class TestPolicyRoutes(BackendVivo):
    """La politica es un dato que el backend guarda y devuelve, tenant a tenant."""

    def test_get_de_un_tenant_sin_politica_devuelve_vacio(self):
        estado, datos = self._get("/v1/policy/nadie-la-configuro")
        self.assertEqual(estado, 200)
        self.assertEqual(datos, {})

    def test_put_seguido_de_get_devuelve_lo_que_se_guardo(self):
        politica = Policy(tenant_id="empresa-put", model_threshold=0.7).a_dict()

        estado_put, _ = self._put("/v1/policy/empresa-put", politica)
        self.assertEqual(estado_put, 200)

        estado_get, datos = self._get("/v1/policy/empresa-put")
        self.assertEqual(estado_get, 200)
        self.assertEqual(datos, politica)

    def test_un_tenant_no_ve_la_politica_de_otro(self):
        self._put("/v1/policy/tenant-a", Policy(tenant_id="tenant-a").a_dict())
        self._put("/v1/policy/tenant-b", Policy(tenant_id="tenant-b").a_dict())

        _, datos_a = self._get("/v1/policy/tenant-a")
        _, datos_b = self._get("/v1/policy/tenant-b")

        self.assertEqual(datos_a["tenant_id"], "tenant-a")
        self.assertEqual(datos_b["tenant_id"], "tenant-b")


class TestRefrescoDeLaPolitica(BackendVivo):
    """El agente pide su politica al backend en segundo plano, sin bloquear."""

    def test_refrescar_deja_la_politica_del_backend_guardada_en_disco(self):
        self._put("/v1/policy/empresa-refresco", Policy(tenant_id="empresa-refresco", model_threshold=0.9).a_dict())
        ruta = Path(self.workdir.name) / "politica-agente.json"

        hilo = policy_store.refrescar_en_segundo_plano(
            f"http://127.0.0.1:{self.port}", "empresa-refresco", ruta
        )
        hilo.join(timeout=5)

        self.assertEqual(policy_store.cargar(ruta).tenant_id, "empresa-refresco")
        self.assertEqual(policy_store.cargar(ruta).model_threshold, 0.9)

    def test_refrescar_sin_politica_en_el_backend_no_deja_nada(self):
        ruta = Path(self.workdir.name) / "politica-inexistente.json"

        hilo = policy_store.refrescar_en_segundo_plano(
            f"http://127.0.0.1:{self.port}", "tenant-sin-politica-nunca-configurado", ruta
        )
        hilo.join(timeout=5)

        self.assertFalse(ruta.exists())


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

    def test_refrescar_la_politica_sin_backend_no_lanza_y_no_bloquea(self):
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        ruta = Path(workdir.name) / "politica.json"

        hilo = policy_store.refrescar_en_segundo_plano(
            f"http://127.0.0.1:{free_port()}", "cualquiera", ruta
        )
        hilo.join(timeout=5)

        # Sin backend, el archivo no se toca: la ultima politica conocida (acá,
        # ninguna) sigue siendo la que se usa.
        self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
