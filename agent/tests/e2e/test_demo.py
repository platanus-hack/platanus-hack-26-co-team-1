"""Demo end-to-end: un navegador real intentando filtrar datos a una IA.

Los seis casos que definen el producto:

  1. IA aprobada + texto limpio  -> pasa, porque el objetivo es que la gente use
                                    la herramienta que la empresa si aprobo
  2. IA aprobada + credenciales  -> se corta el dato, no la herramienta
  3. IA no aprobada              -> se corta el destino (shadow AI)
  4. Dominio desconocido con forma de API de IA -> se corta igual
  5. Sitio interno               -> no se interrumpe el trabajo
  6. El evento registrado        -> no lleva el secreto
"""

from __future__ import annotations

import json
import unittest

from .harness import ProxyHarness

AWS_KEY = "AKIAIOSFODNN7EXAMPLE"

PROMPT_LIMPIO = (
    "Ayudame a escribir el copy de la campana de septiembre para redes sociales."
)

ARCHIVO_SENSIBLE = f"""# credenciales de produccion
AWS_ACCESS_KEY_ID={AWS_KEY}
DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod
"""


class AegisDemo(ProxyHarness, unittest.TestCase):
    def test_1_ia_aprobada_con_texto_limpio_pasa(self):
        page = self.page()
        page.goto("https://claude.ai/", wait_until="domcontentloaded")
        page.fill("#prompt", PROMPT_LIMPIO)
        page.click("#enviar")
        page.wait_for_load_state("domcontentloaded")
        self.assertIn("Respuesta del modelo", page.content())

    def test_2_ia_aprobada_con_archivo_sensible_se_bloquea(self):
        page = self.page()
        self.upload(page, "claude.ai", ARCHIVO_SENSIBLE, PROMPT_LIMPIO)
        contenido = page.content()
        self.assertIn("no debe salir", contenido)
        self.assertIn("aws_access_key_id", contenido)
        self.assertNotIn(AWS_KEY, contenido)
        self.assertIn("credenciales de AWS", contenido)

    def test_3_ia_no_aprobada_se_bloquea_el_destino(self):
        page = self.page()
        page.goto("https://novaai.local/", wait_until="domcontentloaded")
        contenido = page.content()
        self.assertIn("no esta aprobado", contenido)
        self.assertIn("claude.ai", contenido)

    def test_4_dominio_desconocido_con_forma_de_ia_se_bloquea(self):
        page = self.page()
        self.upload(page, "asistente-magico.co", ARCHIVO_SENSIBLE, PROMPT_LIMPIO)
        self.assertIn("no debe salir", page.content())

    def test_5_sitio_interno_no_ia_no_se_interrumpe(self):
        page = self.page()
        self.upload(page, "intranet.acme.co", ARCHIVO_SENSIBLE, PROMPT_LIMPIO)
        self.assertIn("Respuesta del modelo", page.content())

    def test_6_los_eventos_registrados_no_llevan_el_secreto(self):
        page = self.page()
        self.upload(page, "claude.ai", ARCHIVO_SENSIBLE, PROMPT_LIMPIO)
        eventos = self.events()
        self.assertTrue(eventos, "no se registro ningun evento")
        crudo = json.dumps(eventos, ensure_ascii=False)
        self.assertNotIn(AWS_KEY, crudo)
        self.assertNotIn("s3cr3t", crudo)
        bloqueados = [e for e in eventos if e["action"] == "blocked"]
        self.assertTrue(bloqueados)
        self.assertTrue(any(e["detection"] for e in bloqueados))


if __name__ == "__main__":
    unittest.main(verbosity=2)
