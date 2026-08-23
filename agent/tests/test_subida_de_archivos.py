"""El adjunto que se iba sin abrirse.

Los bytes de un archivo arrastrado a ChatGPT no van a chatgpt.com: van a
files.oaiusercontent.com. El embudo preguntaba "¿esto parece un chat?" y una
subida no lo parece, asi que la accion mas comun para sacar un documento entero
no disparaba nada.

La mitad de abajo de este archivo es la que sostiene el arreglo: el embudo existe
para NO escanear el 97% del trafico, y una senal de subida demasiado ancha lo
rompe. Si estos tests se ponen rojos, se volvio a escanear la navegacion normal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aegis_agent.policy import Policy, classify
from aegis_agent.subidas import (
    es_subida_de_archivo,
    ia_que_origina,
    subida_hacia_una_ia,
)
from tests.aislamiento import entorno_aislado
from tests.test_embudo import FakeFlow, FakeRequest, make_addon

ES_IA = lambda host: classify(host, Policy()) not in ("non_ai", "passthrough")

ZIP = b"PK\x03\x04" + b"\x00" * 64
MULTIPART = (
    b'--x\r\nContent-Disposition: form-data; name="file"; filename="nomina.xlsx"'
    b"\r\nContent-Type: application/octet-stream\r\n\r\n" + ZIP
)


class TestReconocerLaSubida(unittest.TestCase):
    def test_multipart_con_archivo(self):
        self.assertTrue(
            es_subida_de_archivo("multipart/form-data; boundary=x", MULTIPART)
        )

    def test_multipart_solo_de_texto_no_es_subida(self):
        """Un formulario sin filename= es texto, y su texto ya lo mira el motor."""

        cuerpo = b'--x\r\nContent-Disposition: form-data; name="mensaje"\r\n\r\nhola'
        self.assertFalse(
            es_subida_de_archivo("multipart/form-data; boundary=x", cuerpo)
        )

    def test_por_content_type(self):
        for tipo in (
            "application/pdf",
            "application/octet-stream",
            "image/png",
            "image/heic",
            "audio/mpeg",
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ):
            with self.subTest(tipo=tipo):
                self.assertTrue(es_subida_de_archivo(tipo, b""))

    def test_por_firma_cuando_el_content_type_miente(self):
        """El archivo es lo que es, no lo que dice el encabezado.

        Renombrar y mentir el Content-Type es la evasion mas barata que existe, y
        es la misma razon por la que detect/files.py mira firmas binarias.
        """

        for firma in (b"%PDF-1.7", b"\x89PNG\r\n", b"\xff\xd8\xff\xe0", b"ID3\x03"):
            with self.subTest(firma=firma):
                self.assertTrue(es_subida_de_archivo("text/plain", firma + b"\x00" * 32))

    def test_un_json_de_conversacion_no_es_una_subida(self):
        cuerpo = json.dumps({"messages": [{"content": "hola"}]}).encode()
        self.assertFalse(es_subida_de_archivo("application/json", cuerpo))


class TestOrigen(unittest.TestCase):
    def test_el_origin_de_la_pestana(self):
        self.assertEqual(
            ia_que_origina("https://chatgpt.com", "", ES_IA), "chatgpt.com"
        )

    def test_el_referer_cuando_no_hay_origin(self):
        self.assertEqual(
            ia_que_origina("", "https://claude.ai/chat/abc", ES_IA), "claude.ai"
        )

    def test_un_origen_que_no_es_ia_no_cuenta(self):
        self.assertIsNone(ia_que_origina("https://intranet.acme.co", "", ES_IA))

    def test_tolera_basura(self):
        for basura in ("", "   ", "null", "chatgpt.com", "://roto"):
            with self.subTest(basura=basura):
                ia_que_origina(basura, "", ES_IA)  # no revienta

    def test_hacen_falta_LAS_DOS_condiciones(self):
        """Ni la subida sola ni el origen solo alcanzan.

        Una subida a un host cualquiera desde una pagina cualquiera es la
        navegacion normal --subir una foto de perfil, adjuntar algo a un ticket--
        y escanearla es exactamente lo que el embudo existe para evitar.
        """

        self.assertIsNone(
            subida_hacia_una_ia("application/pdf", ZIP, "https://jira.acme.co", "", ES_IA)
        )
        self.assertIsNone(
            subida_hacia_una_ia(
                "application/json",
                json.dumps({"messages": []}).encode(),
                "https://chatgpt.com",
                "",
                ES_IA,
            )
        )

    def test_la_subida_hacia_una_ia_devuelve_a_cual(self):
        """Devuelve el host y no un booleano, porque el panel tiene que decirlo.

        "Un archivo salio hacia ChatGPT" y "hubo una subida" no son la misma
        frase para la persona que mira el panel.
        """

        self.assertEqual(
            subida_hacia_una_ia(
                "multipart/form-data; boundary=x",
                MULTIPART,
                "https://chatgpt.com",
                "",
                ES_IA,
            ),
            "chatgpt.com",
        )


class TestElCatalogoDeSubidas(unittest.TestCase):
    """Los hosts donde caen los bytes, y los que tienen un host por region."""

    def test_el_endpoint_de_subida_de_chatgpt_ya_no_es_non_ai(self):
        self.assertNotEqual(
            classify("files.oaiusercontent.com", Policy()), "non_ai"
        )

    def test_bedrock_en_cualquier_region(self):
        for region in ("us-east-1", "eu-west-1", "sa-east-1", "ap-southeast-2"):
            with self.subTest(region=region):
                self.assertNotEqual(
                    classify(f"bedrock-runtime.{region}.amazonaws.com", Policy()),
                    "non_ai",
                )

    def test_vertex_con_y_sin_region(self):
        for host in ("aiplatform.googleapis.com", "us-central1-aiplatform.googleapis.com"):
            with self.subTest(host=host):
                self.assertNotEqual(classify(host, Policy()), "non_ai")

    def test_el_patron_de_blobs_es_estrecho_a_proposito(self):
        """El almacenamiento propio de la empresa no puede volverse un destino de IA.

        Un patron ancho sobre blob.core.windows.net convertiria cada cuenta de
        storage del cliente en trafico a inspeccionar, que es peor que no verlo.
        """

        self.assertNotEqual(
            classify("chatgpt-async-webps-prod-westus3.blob.core.windows.net", Policy()),
            "non_ai",
        )
        self.assertEqual(
            classify("acmenomina.blob.core.windows.net", Policy()), "non_ai"
        )


class TestPorElAddonCompleto(unittest.TestCase):
    """El camino de verdad: entra por request() y tiene que llegar al escaneo."""

    def setUp(self):
        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.queue = Path(self.workdir.name) / "eventos.jsonl"
        self.addon = make_addon(self.queue)

    def _correr(self, host, path, body, headers, method="POST"):
        flow = FakeFlow(FakeRequest(host, path, body, method=method, headers=headers))
        with patch("aegis_agent.proxy.addon.scan_payload") as escaneo:
            escaneo.return_value = type(
                "R", (), {"findings": [], "truncated": False, "views": 1}
            )()
            self.addon.request(flow)
            return escaneo

    def test_el_adjunto_a_chatgpt_ahora_se_escanea(self):
        escaneo = self._correr(
            "algun-blob-desconocido.example.net",
            "/upload/file-abc",
            MULTIPART,
            {
                "Content-Type": "multipart/form-data; boundary=x",
                "Origin": "https://chatgpt.com",
            },
            method="PUT",
        )
        self.assertTrue(
            escaneo.called,
            "el adjunto hacia una IA tiene que llegar al motor, y se estaba yendo entero",
        )

    def test_la_navegacion_normal_sigue_sin_escanearse(self):
        """El contraveneno. Si esto se pone rojo, se rompio el embudo."""

        escaneo = self._correr(
            "jira.acme.co",
            "/rest/api/attachment",
            MULTIPART,
            {
                "Content-Type": "multipart/form-data; boundary=x",
                "Origin": "https://jira.acme.co",
            },
        )
        self.assertFalse(
            escaneo.called, "una subida a un sitio interno no se inspecciona"
        )

    def test_sin_cabeceras_no_revienta(self):
        self._correr("cdn.acme.co", "/asset", ZIP, {})


if __name__ == "__main__":
    unittest.main()
