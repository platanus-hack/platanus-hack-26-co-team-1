"""SupabaseDomainStore: el mismo contrato que DomainStore, pero compartido.

Todo local (aegis-domains.json) sigue funcionando sin Supabase: si no hay
SUPABASE_URL en el entorno, store_from_env() cae al store de JSON de siempre.
Con Supabase, el backend habla PostgREST via urllib -- sin dependencias
nuevas -- y el agente nunca toca la base directamente (solo el backend tiene
la service key).
"""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_backend.store import (  # noqa: E402
    DomainStore,
    SupabaseDomainStore,
    Verdict,
    store_from_env,
)


class _Respuesta:
    def __init__(self, cuerpo, headers=None):
        self._cuerpo = json.dumps(cuerpo).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._cuerpo


def _verdict(domain="acme-chat.co", source="llm_classifier", confidence=0.95):
    return Verdict(
        domain=domain,
        classification="ai_unapproved",
        kind="llm_chat",
        confidence=confidence,
        evidence="Chat con un modelo",
        source=source,
        classified_at=time.time(),
    )


class TestSupabaseDomainStore(unittest.TestCase):
    def setUp(self):
        self.store = SupabaseDomainStore("https://proyecto.supabase.co", "clave-service")

    def test_get_sin_filas_devuelve_none(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.assertIsNone(self.store.get("nadie-lo-conoce.co"))

    def test_get_parsea_la_fila_a_verdict(self):
        fila = {
            "dominio": "acme-chat.co",
            "clasificacion": "ai_unapproved",
            "tipo": "llm_chat",
            "confianza": 0.9,
            "evidencia": "Chat con un modelo",
            "fuente": "llm_classifier",
            "clasificado_en": "2026-01-01T00:00:00Z",
        }
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([fila])
            veredicto = self.store.get("acme-chat.co")

        self.assertEqual(veredicto.domain, "acme-chat.co")
        self.assertEqual(veredicto.classification, "ai_unapproved")
        self.assertEqual(veredicto.source, "llm_classifier")

    def test_get_pide_el_dominio_normalizado_en_la_query(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.store.get("ACME-CHAT.CO.")

        peticion = urlopen.call_args[0][0]
        self.assertIn("dominio=eq.acme-chat.co", peticion.full_url)

    def test_get_sin_red_no_lanza(self):
        import urllib.error

        with patch(
            "aegis_backend.store.urllib.request.urlopen",
            side_effect=urllib.error.URLError("caido"),
        ):
            self.assertIsNone(self.store.get("acme-chat.co"))

    def test_put_manda_un_upsert_con_los_campos_mapeados(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.store.put(_verdict())

        peticion = urlopen.call_args[0][0]
        self.assertEqual(peticion.get_method(), "POST")
        self.assertEqual(
            peticion.get_header("Prefer"), "resolution=merge-duplicates,return=minimal"
        )
        cuerpo = json.loads(peticion.data)[0]
        self.assertEqual(cuerpo["dominio"], "acme-chat.co")
        self.assertEqual(cuerpo["clasificacion"], "ai_unapproved")
        self.assertEqual(cuerpo["fuente"], "llm_classifier")

    def test_put_calcula_vence_en_segun_el_ttl(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.store.put(_verdict(source="llm_classifier", confidence=0.95))

        cuerpo = json.loads(urlopen.call_args[0][0].data)[0]
        self.assertIsNotNone(cuerpo["vence_en"])

    def test_put_manual_review_no_pone_fecha_de_vencimiento(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.store.put(_verdict(source="manual_review", confidence=1.0))

        cuerpo = json.loads(urlopen.call_args[0][0].data)[0]
        self.assertIsNone(cuerpo["vence_en"])

    def test_count_lee_el_content_range(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([], headers={"Content-Range": "0-24/8342"})
            self.assertEqual(self.store.count(), 8342)

    def test_count_sin_red_devuelve_cero(self):
        import urllib.error

        with patch(
            "aegis_backend.store.urllib.request.urlopen",
            side_effect=urllib.error.URLError("caido"),
        ):
            self.assertEqual(self.store.count(), 0)

    def test_all_domains_devuelve_ordenado(self):
        filas = [{"dominio": "zeta.co"}, {"dominio": "acme.co"}]
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta(filas)
            self.assertEqual(self.store.all_domains(), ["acme.co", "zeta.co"])

    def test_desde_filtra_por_actualizado_en_en_la_query(self):
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([])
            self.store.desde("2026-01-01T00:00:00Z")

        peticion = urlopen.call_args[0][0]
        self.assertIn("actualizado_en=gte.2026-01-01T00:00:00Z", peticion.full_url)

    def test_desde_devuelve_veredictos(self):
        fila = {
            "dominio": "nuevo.co",
            "clasificacion": "non_ai",
            "tipo": "non_ai",
            "confianza": 0.1,
            "evidencia": "x",
            "fuente": "heuristic",
            "clasificado_en": "2026-01-01T00:00:00Z",
        }
        with patch("aegis_backend.store.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Respuesta([fila])
            veredictos = self.store.desde("2026-01-01T00:00:00Z")

        self.assertEqual(len(veredictos), 1)
        self.assertEqual(veredictos[0].domain, "nuevo.co")


class TestStoreFromEnv(unittest.TestCase):
    def test_sin_variables_de_entorno_usa_el_store_de_json(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("SUPABASE_URL", None)
            os.environ.pop("SUPABASE_SERVICE_KEY", None)
            resultado = store_from_env(Path("aegis-domains.json"))

        self.assertIsInstance(resultado, DomainStore)

    def test_con_variables_de_entorno_usa_supabase(self):
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://proyecto.supabase.co",
                "SUPABASE_SERVICE_KEY": "clave-service",
            },
        ):
            resultado = store_from_env(Path("aegis-domains.json"))

        self.assertIsInstance(resultado, SupabaseDomainStore)


if __name__ == "__main__":
    unittest.main()
