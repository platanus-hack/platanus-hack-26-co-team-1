"""El dato sensible es lo que hace crecer la lista negra, no solo la forma.

Antes de esto, un secreto hacia un destino que no parece IA (un POST comun, sin
streaming, sin "messages" en el body) salia sin que una sola regla lo mirara:
looks_like_ai_api decia que no y _inspect volvia sin escanear nada. Estos tests
fijan el nuevo comportamiento: un barrido barato sobre el preview decide si el
destino merece el escaneo completo, y si encuentra algo, tres cosas pasan --
se registra, se encola el dominio para que Haiku lo investigue, y se actua
segun unknown_domain_action.
"""

import tempfile
import unittest
from pathlib import Path

from aegis_agent.signals import UMBRAL

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"


class FakeRequest:
    def __init__(self, host, path, body, method="POST"):
        self.pretty_host = host
        self.path = path
        self.method = method
        self._body = body
        self.query = None
        self.headers = {"Accept": "application/json"}

    def get_content(self, strict=True):
        return self._body

    @property
    def raw_content(self):
        return self._body


class FakeFlow:
    def __init__(self, request):
        self.request = request
        self.response = None


def make_addon(tmp_queue, **overrides):
    from aegis_agent.policy import Policy
    from aegis_agent.proxy.addon import Aegis

    addon = Aegis()
    addon.queue = tmp_queue
    addon.domains.enabled = False
    if overrides:
        addon.policy = Policy(**overrides)
    return addon


class TestDestinoDesconocido(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"

    def _cuerpo_con_secreto(self):
        return f'{{"nota": "AWS_ACCESS_KEY_ID={AWS_KEY}"}}'.encode()

    def _post(self, addon, host="portal-interno.co", path="/api/enviar", body=None):
        from aegis_agent.proxy.addon import Aegis  # noqa: F401  (import local, evita ciclos en test)

        flow = FakeFlow(FakeRequest(host, path, body))
        addon.request(flow)
        return flow

    def test_por_defecto_registra_pero_no_bloquea(self):
        addon = make_addon(self.queue)
        flow = self._post(addon, body=self._cuerpo_con_secreto())

        self.assertIsNone(flow.response)
        contenido = self.queue.read_text(encoding="utf-8")
        self.assertIn("aws_access_key_id", contenido)

    def test_por_defecto_encola_el_dominio_para_investigar(self):
        addon = make_addon(self.queue)
        self._post(addon, host="portal-interno.co", body=self._cuerpo_con_secreto())

        self.assertGreaterEqual(addon.signals.score("portal-interno.co"), UMBRAL)

    def test_modo_block_content_corta_el_envio(self):
        addon = make_addon(self.queue, unknown_domain_action="block_content")
        flow = self._post(addon, body=self._cuerpo_con_secreto())

        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 403)

    def test_modo_allow_reproduce_el_embudo_de_siempre(self):
        addon = make_addon(self.queue, unknown_domain_action="allow")
        flow = self._post(addon, body=self._cuerpo_con_secreto())

        self.assertIsNone(flow.response)
        self.assertFalse(self.queue.exists() and self.queue.read_text(encoding="utf-8").strip())

    def test_trafico_limpio_sigue_sin_generar_nada(self):
        addon = make_addon(self.queue)
        flow = self._post(addon, body=b'{"customer_id": 42, "total": 19900}')

        self.assertIsNone(flow.response)
        self.assertFalse(self.queue.exists() and self.queue.read_text(encoding="utf-8").strip())
        self.assertEqual(addon.signals.score("portal-interno.co"), 0)


if __name__ == "__main__":
    unittest.main()
