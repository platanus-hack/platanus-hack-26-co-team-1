"""El destino filtra antes que el contenido.

Sin este embudo el agente escanea cada POST de la navegacion normal: gasta CPU
en cada clic y llena el panel de hallazgos que a nadie le importan, porque el
dato nunca estuvo yendo a un modelo. Se detecto corriendo contra trafico real.
"""

import unittest

from tests.aislamiento import entorno_aislado
from unittest.mock import patch

from aegis_agent.policy import Policy, classify, looks_like_ai_api


class FakeRequest:
    def __init__(self, host, path, body, method="POST"):
        self.pretty_host = host
        self.path = path
        self.method = method
        self._body = body
        self.query = None

    def get_content(self, strict=True):
        return self._body

    @property
    def raw_content(self):
        return self._body


class FakeFlow:
    def __init__(self, request):
        self.request = request
        self.response = None


def make_addon(tmp_queue):
    from aegis_agent.proxy.addon import Aegis

    with entorno_aislado(tmp_queue.parent):
        addon = Aegis()
    addon.queue = tmp_queue
    addon.domains.enabled = False
    return addon


class TestEmbudo(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"
        self.addon = make_addon(self.queue)

    def _run(self, host, path, body):
        flow = FakeFlow(FakeRequest(host, path, body))
        with patch("aegis_agent.proxy.addon.scan_payload") as escaneo:
            escaneo.return_value = type(
                "R", (), {"findings": [], "truncated": False, "views": 1}
            )()
            self.addon.request(flow)
            return flow, escaneo

    def test_un_sitio_normal_no_se_escanea(self):
        cuerpo = b'{"customer_id": 42, "total": 19900}'
        _, escaneo = self._run("facturacion.acme.co", "/api/invoices", cuerpo)
        escaneo.assert_not_called()

    def test_un_sitio_normal_no_ensucia_el_panel(self):
        self._run("analytics.acme.co", "/collect", b'{"event":"click"}')
        self.assertFalse(self.queue.exists() and self.queue.read_text(encoding="utf-8").strip())

    def test_una_ia_aprobada_si_se_escanea(self):
        _, escaneo = self._run("claude.ai", "/api/chat", b"hola")
        escaneo.assert_called_once()

    def test_un_dominio_con_forma_de_ia_si_se_escanea(self):
        cuerpo = b'{"model":"x","messages":[]}'
        _, escaneo = self._run("raro.co", "/v1/chat/completions", cuerpo)
        escaneo.assert_called_once()

    def test_el_embudo_coincide_con_la_politica(self):
        # Si classify dice non_ai y la forma no delata nada, no hay inspeccion.
        self.assertEqual(classify("facturacion.acme.co", Policy()), "non_ai")
        self.assertFalse(looks_like_ai_api("/api/invoices", '{"customer_id":42}'))


if __name__ == "__main__":
    unittest.main()
