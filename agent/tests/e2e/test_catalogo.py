"""Recorre el catalogo de shadow AI con un navegador de verdad.

Los tests unitarios verifican la clasificacion; este verifica que el bloqueo
llega hasta la pantalla. Son cosas distintas: una regla puede clasificar bien y
el proxy igual dejar pasar el trafico por un detalle de la ruta o del metodo.

El upstream simulado responde a cualquier host, asi que si en alguno de estos
casos aparece la pagina del servicio en vez de la de Aegis, es una fuga real.
"""

from __future__ import annotations

import unittest

from aegis_agent.catalog import CATEGORIES
from aegis_agent.policy import Policy

from .harness import ProxyHarness

POLICY = Policy()

# Dos dominios por categoria alcanzan para cubrir las siete familias sin que la
# suite tarde un minuto. La cobertura exhaustiva la dan los tests unitarios.
POR_CATEGORIA = 2

MUESTRA: list[tuple[str, str]] = [
    (categoria, dominio)
    for categoria, dominios in CATEGORIES.items()
    for dominio in sorted(dominios - POLICY.approved_ai)[:POR_CATEGORIA]
]

SENSIBLE = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"


class CatalogoE2E(ProxyHarness, unittest.TestCase):
    def test_cada_categoria_del_catalogo_se_bloquea_en_pantalla(self):
        for categoria, dominio in MUESTRA:
            with self.subTest(categoria=categoria, dominio=dominio):
                page = self.page()
                page.goto(f"https://{dominio}/", wait_until="domcontentloaded")
                contenido = page.content()
                self.assertIn("no esta aprobado", contenido)
                self.assertNotIn("Enviar", contenido)

    def test_los_subdominios_tambien_se_bloquean_en_pantalla(self):
        for _, dominio in MUESTRA[:6]:
            with self.subTest(dominio=f"app.{dominio}"):
                page = self.page()
                page.goto(f"https://app.{dominio}/", wait_until="domcontentloaded")
                self.assertIn("no esta aprobado", page.content())

    def test_la_ia_aprobada_sigue_usable_con_trabajo_normal(self):
        # El producto no sirve de nada si para protegerte te deja sin herramienta.
        for dominio in sorted(POLICY.approved_ai):
            with self.subTest(dominio=dominio):
                page = self.page()
                page.goto(f"https://{dominio}/", wait_until="domcontentloaded")
                page.fill("#prompt", "Resumime este texto en tres vinetas, por favor")
                page.click("#enviar")
                page.wait_for_load_state("domcontentloaded")
                self.assertIn("Respuesta del modelo", page.content())

    def test_un_archivo_sensible_se_corta_en_toda_ia_aprobada(self):
        for dominio in sorted(POLICY.approved_ai):
            with self.subTest(dominio=dominio):
                page = self.page()
                self.upload(page, dominio, SENSIBLE)
                self.assertIn("no debe salir", page.content())

    def test_el_evento_queda_registrado_por_cada_bloqueo(self):
        antes = len(self.events())
        page = self.page()
        page.goto("https://otter.ai/", wait_until="domcontentloaded")
        self.assertGreater(len(self.events()), antes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
