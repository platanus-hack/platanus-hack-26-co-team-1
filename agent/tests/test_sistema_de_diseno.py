"""Que las superficies de Aegis se vean como un solo producto.

Aegis se le muestra a la persona en tres lugares que no comparten stack: el
front principal (Angular + Tailwind), la pagina de bloqueo y el panel (HTML que
arma Python, porque tienen que funcionar sin build y sin red).

Cuando cada superficie eligio su paleta, el resultado fue que la persona veia
una marca en la landing y otra distinta **en el momento que mas importa**:
cuando algo se bloquea. La pagina de bloqueo llego a ser gris oscura mientras el
producto era claro y calido.

`ui/tokens.py` es el espejo de `frontend/tailwind.config.js`. Estos tests son lo
que hace que siga siendolo cuando alguien cambie un color de un lado.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from aegis_agent.panel.demo_data import semana_simulada
from aegis_agent.panel.metrics import compute, repeat_offenders
from aegis_agent.panel.render import render
from aegis_agent.proxy import blockpage
from aegis_agent.ui import tokens

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
TAILWIND = REPO / "frontend" / "tailwind.config.js"

# La paleta oscura que tenian estas paginas antes de unificarlas. Si alguno de
# estos vuelve a aparecer, es que se volvio a escribir un color a mano.
PALETA_VIEJA = ("#0f1115", "#171a21", "#e8eaed", "#262b36", "#5b8def", "#8b93a7")


def _pagina_de_bloqueo() -> str:
    return blockpage.content_blocked(
        "claude.ai",
        "aws_access_key_id",
        "AKIA****",
        {"title": "T", "why": "W", "what_to_do": "Q"},
        aprobada=True,
    )


def _panel() -> str:
    eventos = semana_simulada()
    return render(compute(eventos), repeat_offenders(eventos), "acme")


class TestLasDosSuperficiesUsanLosTokens(unittest.TestCase):
    def test_la_pagina_de_bloqueo_usa_el_fondo_y_el_acento_del_producto(self):
        html = _pagina_de_bloqueo()
        self.assertIn(tokens.BG, html)
        self.assertIn(tokens.ACCENT, html)

    def test_el_panel_usa_el_fondo_y_el_acento_del_producto(self):
        html = _panel()
        self.assertIn(tokens.BG, html)
        self.assertIn(tokens.ACCENT, html)

    def test_ninguna_conserva_la_paleta_oscura(self):
        for nombre, html in (("bloqueo", _pagina_de_bloqueo()), ("panel", _panel())):
            for color in PALETA_VIEJA:
                with self.subTest(pagina=nombre, color=color):
                    self.assertNotIn(color, html)

    def test_las_dos_muestran_el_mismo_escudo(self):
        # Es la marca, y era literalmente el mismo SVG copiado en dos archivos.
        self.assertIn(tokens.ESCUDO_SVG, _pagina_de_bloqueo())
        self.assertIn(tokens.ESCUDO_SVG, _panel())

    def test_la_pagina_de_bloqueo_no_depende_de_la_red(self):
        # Se renderiza dentro de un proxy que acaba de cortar una conexion: una
        # hoja de estilos o una fuente remota la dejarian sin estilos justo ahi.
        html = _pagina_de_bloqueo()
        self.assertNotIn("<link", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)


class TestNoSeSeparanDelFront(unittest.TestCase):
    """El espejo de tailwind.config.js, comprobado contra el archivo de verdad.

    Se salta si el front no esta en esta rama: `ui/tokens.py` tiene que poder
    vivir sin el, igual que el agente vive sin el modelo. Cuando el front se
    integre, este test empieza a cuidar los dos lados solo.
    """

    @unittest.skipUnless(TAILWIND.exists(), "el front no esta en esta rama")
    def test_cada_color_del_front_existe_igual_en_los_tokens(self):
        crudo = TAILWIND.read_text(encoding="utf-8")
        bloque = re.search(r"aegis:\s*\{(.+?)\}", crudo, re.S)
        self.assertIsNotNone(bloque, "no se encontro la paleta aegis en tailwind.config.js")

        del_front = dict(re.findall(r"(\w+):\s*'(#[0-9a-fA-F]{6})'", bloque.group(1)))
        self.assertTrue(del_front, "no se pudo leer ningun color del front")

        de_python = {
            nombre.lower(): getattr(tokens, nombre)
            for nombre in dir(tokens)
            if nombre.isupper() and isinstance(getattr(tokens, nombre), str)
            and getattr(tokens, nombre).startswith("#")
        }

        for nombre, color in del_front.items():
            with self.subTest(color=nombre):
                self.assertIn(nombre, de_python, f"falta {nombre} en ui/tokens.py")
                self.assertEqual(
                    de_python[nombre].lower(),
                    color.lower(),
                    f"{nombre} cambio en el front y no en ui/tokens.py",
                )


if __name__ == "__main__":
    unittest.main()
