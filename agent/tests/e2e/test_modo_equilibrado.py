"""Modo equilibrado: no se corta el sitio, se corta el envio.

Bloquear la herramienta que la gente ya usa termina en excepciones, VPNs y
telefonos personales, que es exactamente donde nadie ve nada. Este modo deja
usar la IA no aprobada y se asegura de que no salga ni un dato sensible, mientras
el uso queda igual registrado para la empresa.
"""

from __future__ import annotations

import unittest

from .harness import ProxyHarness

SENSIBLE = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
PROMPT_LIMPIO = "Resumime las ideas principales de este texto en tres vinetas"


class ModoEquilibradoE2E(ProxyHarness, unittest.TestCase):
    MODO = "equilibrado"

    def test_la_ia_no_aprobada_abre_normal(self):
        page = self.page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        contenido = page.content()
        self.assertNotIn("no esta aprobado", contenido)
        self.assertIn("Enviar", contenido)

    def test_un_prompt_de_trabajo_llega_al_modelo(self):
        page = self.page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT_LIMPIO)
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")
        self.assertIn("Respuesta del modelo", page.content())

    def test_un_prompt_con_credenciales_no_llega(self):
        page = self.page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        page.fill("#prompt", f"Ayudame con esto: {SENSIBLE}")
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")
        contenido = page.content()
        self.assertIn("no debe salir", contenido)
        self.assertIn("no aprobada", contenido)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", contenido)

    def test_un_archivo_critico_tampoco(self):
        page = self.page()
        self.upload(page, "novaai.local", SENSIBLE)
        self.assertIn("no debe salir", page.content())

    def test_el_uso_de_la_herramienta_no_aprobada_queda_registrado(self):
        # La visibilidad del shadow AI no se pierde por dejar usar la herramienta:
        # es justamente lo que la empresa necesita ver en el panel.
        page = self.page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        usos = [
            e
            for e in self.events()
            if e["destination"]["domain"] == "novaai.local"
            and e["destination"]["classification"] == "ai_unapproved"
        ]
        self.assertTrue(usos, "no se registro el uso de la herramienta no aprobada")

    def test_la_ia_aprobada_sigue_igual(self):
        page = self.page()
        page.goto("https://claude.ai/", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT_LIMPIO)
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")
        self.assertIn("Respuesta del modelo", page.content())


if __name__ == "__main__":
    unittest.main(verbosity=2)
