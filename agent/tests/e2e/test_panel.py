"""El panel visto por un navegador, con datos de una semana simulada."""

from __future__ import annotations

import json
import random
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from aegis_agent.panel.server import serve

PORT = 8788

AREAS = {
    "marketing": ["u_ana", "u_pablo"],
    "contabilidad": ["u_carmen"],
    "ingenieria": ["u_diego", "u_sofia"],
    "recursos humanos": ["u_lucia"],
}

DESTINOS = [
    ("claude.ai", "ai_approved"),
    ("chatgpt.com", "ai_unapproved"),
    ("gemini.google.com", "ai_unapproved"),
    ("otter.ai", "ai_unapproved"),
    ("asistente-magico.co", "ai_unknown"),
]

DETECCIONES = [
    ("aws_access_key_id", "secret", "critical"),
    ("db_connection_string", "secret", "critical"),
    ("csv_pii_export", "internal_data", "critical"),
    ("bulk_pii_export", "internal_data", "critical"),
    ("sql_insert_rows", "internal_data", "high"),
    ("email_address", "pii", "medium"),
    ("confidentiality_marker", "internal_data", "medium"),
]


def semana_simulada(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    eventos = []
    for indice in range(120):
        area = rng.choice(list(AREAS))
        user = rng.choice(AREAS[area])
        domain, classification = rng.choice(DESTINOS)
        rule, category, severity = rng.choice(DETECCIONES)
        action = "blocked" if severity == "critical" else rng.choice(["warned", "blocked"])
        eventos.append(
            {
                "event_id": f"e{indice}",
                "tenant_id": "acme",
                "actor": {"user_id": user, "area": area, "role": "employee"},
                "destination": {
                    "domain": domain,
                    "classification": classification,
                    "process": "browser",
                },
                "detection": {
                    "rule_id": rule,
                    "category": category,
                    "severity": severity,
                    "confidence": 0.95,
                    "engine": "t1_rules",
                    "evidence": "AKIA****" if category == "secret" else "<pii x40>",
                },
                "action": action,
                "payload_stats": {"bytes": rng.randint(200, 90000), "truncated": False},
                "occurred_at": f"2026-08-{18 + indice % 5:02d}T{9 + indice % 9:02d}:12:00Z",
                "agent_version": "0.1.0",
            }
        )
    # Un caso deliberado de reincidencia: la misma persona, el mismo error.
    eventos.extend(
        {
            "event_id": f"r{i}",
            "tenant_id": "acme",
            "actor": {"user_id": "u_pablo", "area": "marketing", "role": "employee"},
            "destination": {
                "domain": "chatgpt.com",
                "classification": "ai_unapproved",
                "process": "browser",
            },
            "detection": {
                "rule_id": "aws_access_key_id",
                "category": "secret",
                "severity": "critical",
                "confidence": 0.99,
                "engine": "t1_rules",
                "evidence": "AKIA****",
            },
            "action": "blocked",
            "payload_stats": {"bytes": 900, "truncated": False},
            "occurred_at": f"2026-08-2{i}T11:00:00Z",
            "agent_version": "0.1.0",
        }
        for i in range(1, 5)
    )
    return eventos


class PanelE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workdir = tempfile.TemporaryDirectory()
        cls.queue = Path(cls.workdir.name) / "eventos.jsonl"
        with open(cls.queue, "w", encoding="utf-8") as handle:
            for evento in semana_simulada():
                handle.write(json.dumps(evento, ensure_ascii=False) + "\n")

        cls.server = serve(cls.queue, PORT)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.workdir.cleanup()

    def _page(self):
        context = self.browser.new_context(viewport={"width": 1280, "height": 1600})
        self.addCleanup(context.close)
        page = context.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        return page

    def test_el_panel_carga_con_las_secciones_clave(self):
        page = self._page()
        contenido = page.content()
        for seccion in (
            "Panel de la empresa",
            "Destinos mas frecuentes",
            "Que se intenta enviar",
            "Riesgo por area",
            "Shadow AI descubierta",
            "Personas que necesitan acompanamiento",
        ):
            with self.subTest(seccion=seccion):
                self.assertIn(seccion, contenido)

    def test_muestra_las_metricas_del_periodo(self):
        page = self._page()
        contenido = page.content()
        self.assertIn("Fugas evitadas", contenido)
        self.assertIn("Servicios de IA no aprobados en uso", contenido)
        self.assertIn("chatgpt.com", contenido)
        self.assertIn("asistente-magico.co", contenido)

    def test_senala_a_quien_repite_el_mismo_error(self):
        page = self._page()
        contenido = page.content()
        self.assertIn("u_pablo", contenido)
        self.assertIn("repite:", contenido)

    def test_la_api_de_metricas_responde_json(self):
        page = self._page()
        respuesta = page.request.get(f"http://127.0.0.1:{PORT}/api/metrics")
        self.assertEqual(respuesta.status, 200)
        datos = respuesta.json()
        self.assertGreater(datos["metrics"]["total"], 100)
        self.assertIn("u_pablo", datos["repeats"])

    def test_el_panel_no_expone_contenido(self):
        page = self._page()
        contenido = page.content()
        for filtrado in ("AKIAIOSFODNN7EXAMPLE", "postgres://admin", "s3cr3t"):
            with self.subTest(filtrado=filtrado):
                self.assertNotIn(filtrado, contenido)

    def test_captura_para_revision_visual(self):
        page = self._page()
        destino = Path(__file__).resolve().parent / "panel.png"
        page.screenshot(path=str(destino), full_page=True)
        self.assertTrue(destino.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
