"""Cobertura del shadow AI: el catalogo entero y lo que el catalogo no cubre.

Dos frentes distintos. El primero es aburrido y necesario: que ningun dominio de
la lista se escape por un subdominio o una mayuscula. El segundo es el que
importa de verdad: los servicios que no estan en ninguna lista, que son la
mayoria y los que aparecen cada semana.
"""

import unittest

from aegis_agent.catalog import AI_DOMAINS, CATEGORIES, category_of
from aegis_agent.policy import Policy, classify, decide, looks_like_ai_api

POLICY = Policy()
UNAPPROVED = sorted(AI_DOMAINS - POLICY.approved_ai)


class TestCatalogoCompleto(unittest.TestCase):
    def test_todo_el_catalogo_no_aprobado_se_bloquea(self):
        for domain in UNAPPROVED:
            with self.subTest(domain=domain):
                self.assertEqual(classify(domain, POLICY), "ai_unapproved")

    def test_todo_el_catalogo_no_aprobado_corta_el_destino(self):
        for domain in UNAPPROVED:
            with self.subTest(domain=domain):
                action = decide(classify(domain, POLICY), set(), POLICY)
                self.assertEqual(action, "block_destination")

    def test_los_subdominios_no_son_una_puerta_de_atras(self):
        for domain in UNAPPROVED[:40]:
            for prefix in ("www.", "app.", "eu.", "api.beta."):
                with self.subTest(host=prefix + domain):
                    self.assertEqual(classify(prefix + domain, POLICY), "ai_unapproved")

    def test_mayusculas_y_punto_final_no_evaden(self):
        for host in ("ChatGPT.com", "OTTER.AI", "midjourney.com.", "Api.Groq.Com"):
            with self.subTest(host=host):
                self.assertEqual(classify(host, POLICY), "ai_unapproved")

    def test_la_ia_aprobada_no_se_corta_por_destino(self):
        for domain in sorted(POLICY.approved_ai):
            with self.subTest(domain=domain):
                self.assertEqual(classify(domain, POLICY), "ai_approved")
                self.assertEqual(decide("ai_approved", set(), POLICY), "allow")

    def test_cada_dominio_pertenece_a_una_categoria(self):
        for domain in sorted(AI_DOMAINS):
            with self.subTest(domain=domain):
                self.assertIsNotNone(category_of(domain))

    def test_hay_cobertura_mas_alla_del_chat(self):
        # El riesgo no es solo ChatGPT: un transcriptor de reuniones se lleva
        # tanta informacion como un chat y nadie lo tiene en el radar.
        for name in ("meetings", "writing", "code", "model_api", "media"):
            with self.subTest(categoria=name):
                self.assertGreaterEqual(len(CATEGORIES[name]), 8)


class TestShadowAiSinCatalogar(unittest.TestCase):
    """Servicios que NO estan en ninguna lista y aun asi se delatan.

    Esta es la unica defensa contra el servicio que se lanzo ayer, y es la
    diferencia entre un producto y una lista negra que envejece.
    """

    CASOS = {
        "openai_compatible": (
            "/v1/chat/completions",
            '{"model":"llama-3","messages":[{"role":"user","content":"hola"}]}',
        ),
        "anthropic_like": (
            "/v1/messages",
            '{"model":"claude","max_tokens":1024,"messages":[]}',
        ),
        "gemini_like": (
            "/v1beta/models/x:generateContent",
            '{"contents":[{"parts":[{"text":"hola"}]}]}',
        ),
        "ollama_local": ("/api/generate", '{"model":"mistral","prompt":"hola"}'),
        "huggingface_like": ("/models/bert", '{"inputs":"hola","parameters":{}}'),
        "replicate_like": ("/v1/predictions", '{"version":"abc","input":{}}'),
        "bedrock_like": ("/model/x/converse", '{"messages":[],"system":[]}'),
        "embeddings": ("/v1/embeddings", '{"model":"e5","input":"texto"}'),
        "transcripcion": ("/v1/audio/transcriptions", "multipart con audio"),
        "asistente_propio": ("/api/asistente/preguntar", "texto plano"),
        "agente": ("/agent/run", '{"prompt":"x","stream":true}'),
        "sin_pista_en_ruta": (
            "/procesar",
            '{"model":"gpt-4o","temperature":0.7,"messages":[]}',
        ),
    }

    def test_se_detectan_por_la_forma_del_request(self):
        for nombre, (path, body) in self.CASOS.items():
            with self.subTest(caso=nombre):
                self.assertTrue(looks_like_ai_api(path, body))


class TestNoRompeApisNormales(unittest.TestCase):
    CASOS = {
        "facturacion": ("/api/invoices", '{"customer_id":42,"total":19900}'),
        "crm": ("/api/v2/contacts", '{"name":"Ana","email":"a@acme.co"}'),
        "login": ("/auth/login", '{"user":"ana","password":"x"}'),
        "subida_interna": ("/documentos/subir", "multipart con un pdf"),
        "telemetria": ("/collect", '{"event":"click","ts":1723}'),
        "pagos": ("/v1/charges", '{"amount":1000,"currency":"cop"}'),
    }

    def test_no_se_confunden_con_una_ia(self):
        for nombre, (path, body) in self.CASOS.items():
            with self.subTest(caso=nombre):
                self.assertFalse(looks_like_ai_api(path, body))


if __name__ == "__main__":
    unittest.main()
