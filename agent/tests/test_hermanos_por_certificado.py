"""Cuando un host se confirma como IA, su certificado TLS ya delata a la familia.

El proxy termina el handshake antes de decidir nada: para cuando se sabe que
chatgpt.com es una IA, ya se tiene su certificado, y los SAN casi siempre
listan los dominios hermanos (chat.openai.com, api.openai.com). Es descubrimiento
gratis -- cero consultas de red extra -- pero hay que cuidarse de los
certificados de CDN compartida, que listan cientos de dominios de clientes que
no tienen nada que ver entre si.
"""

import unittest

from aegis_agent.cert_siblings import hermanos


class TestHermanos(unittest.TestCase):
    def test_encuentra_los_hermanos_del_certificado(self):
        resultado = hermanos(
            cn="chatgpt.com",
            host="chatgpt.com",
            altnames=["chatgpt.com", "chat.openai.com", "api.openai.com"],
        )
        self.assertEqual(resultado, ["api.openai.com", "chat.openai.com"])

    def test_no_se_incluye_a_si_mismo(self):
        resultado = hermanos(cn="claude.ai", host="claude.ai", altnames=["claude.ai"])
        self.assertEqual(resultado, [])

    def test_ignora_wildcards_normalizandolos(self):
        resultado = hermanos(
            cn="*.openai.com",
            host="api.openai.com",
            altnames=["*.openai.com", "openai.com"],
        )
        self.assertEqual(resultado, ["openai.com"])

    def test_un_certificado_de_cdn_compartida_no_encola_nada(self):
        # Cloudflare y similares listan cientos de dominios de clientes
        # distintos en un solo certificado. Ninguno es "hermano" de nadie.
        muchos = [f"cliente-{i}.example.net" for i in range(200)]
        resultado = hermanos(cn="sni.cloudflaressl.com", host="acme.com", altnames=muchos)
        self.assertEqual(resultado, [])

    def test_el_cn_tiene_que_corresponder_al_host(self):
        # Si el CN no tiene nada que ver con el host que se esta mirando, el
        # certificado no es realmente "de" ese host y no se puede confiar en
        # sus SAN.
        resultado = hermanos(
            cn="otroservicio.net",
            host="acme.com",
            altnames=["acme.com", "otro-hermano.acme.com"],
        )
        self.assertEqual(resultado, [])

    def test_sin_cn_igual_funciona_si_los_san_son_pocos(self):
        resultado = hermanos(cn=None, host="acme.com", altnames=["acme.com", "chat.acme.com"])
        self.assertEqual(resultado, ["chat.acme.com"])

    def test_sin_altnames_no_hay_hermanos(self):
        self.assertEqual(hermanos(cn="acme.com", host="acme.com", altnames=[]), [])


if __name__ == "__main__":
    unittest.main()


class FakeGeneralName:
    def __init__(self, value):
        self.value = value


class FakeCert:
    def __init__(self, cn, altnames):
        self.cn = cn
        self.altnames = [FakeGeneralName(v) for v in altnames]


class FakeServerConn:
    def __init__(self, cert):
        self.certificate_list = [cert] if cert else []


class FakeRequest:
    def __init__(self, host, path="/", body=b"", method="GET"):
        self.pretty_host = host
        self.path = path
        self.method = method
        self._body = body
        self.query = None
        self.headers = {"Accept": "text/html"}

    def get_content(self, strict=True):
        return self._body

    @property
    def raw_content(self):
        return self._body


class FakeFlow:
    def __init__(self, request, cert=None):
        self.request = request
        self.response = None
        self.server_conn = FakeServerConn(cert)


def make_addon(tmp_queue):
    from aegis_agent.proxy.addon import Aegis

    addon = Aegis()
    addon.queue = tmp_queue
    addon.domains.enabled = False
    return addon


class TestDescubrimientoDeHermanos(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"
        self.addon = make_addon(self.queue)
        self.parche = patch.object(self.addon.domains, "request_classification")
        self.mock_pedido = self.parche.start()
        self.addCleanup(self.parche.stop)

    def test_una_ia_conocida_encola_a_sus_hermanos(self):
        cert = FakeCert(cn="chatgpt.com", altnames=["chatgpt.com", "chat.openai.com"])
        flow = FakeFlow(FakeRequest("chatgpt.com"), cert=cert)

        self.addon.request(flow)

        self.mock_pedido.assert_called_once_with("chat.openai.com")

    def test_no_vuelve_a_mirar_el_certificado_en_el_siguiente_request(self):
        cert = FakeCert(cn="chatgpt.com", altnames=["chatgpt.com", "chat.openai.com"])

        self.addon.request(FakeFlow(FakeRequest("chatgpt.com"), cert=cert))
        self.addon.request(FakeFlow(FakeRequest("chatgpt.com"), cert=cert))

        self.assertEqual(self.mock_pedido.call_count, 1)

    def test_un_flow_sin_certificado_no_revienta(self):
        flow = FakeFlow(FakeRequest("chatgpt.com"), cert=None)

        self.addon.request(flow)  # no debe lanzar

        self.mock_pedido.assert_not_called()

    def test_un_sitio_normal_no_dispara_nada(self):
        cert = FakeCert(cn="facturacion.acme.co", altnames=["facturacion.acme.co"])
        flow = FakeFlow(FakeRequest("facturacion.acme.co"), cert=cert)

        self.addon.request(flow)

        self.mock_pedido.assert_not_called()
