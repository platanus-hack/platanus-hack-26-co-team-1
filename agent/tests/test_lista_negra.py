"""La comparacion de dominios tiene que ser instantanea, sin importar el tamano.

_match_length recorria todo el conjunto de dominios en cada request: barato con
120 dominios semilla, pero lineal por peticion con una lista que crece sola a
miles. Estos tests fijan el comportamiento de la caminata de sufijos que lo
reemplaza (agent/aegis_agent/suffixes.py) y muestran que el costo no depende
del tamano del conjunto.
"""

from __future__ import annotations

import time
import unittest

from aegis_agent.suffixes import most_specific_match, walk


class TestWalk(unittest.TestCase):
    def test_el_host_completo_es_el_primer_sufijo(self):
        self.assertEqual(
            walk("api.chat.acme.com"),
            ["api.chat.acme.com", "chat.acme.com", "acme.com", "com"],
        )

    def test_normaliza_mayusculas_y_punto_final(self):
        self.assertEqual(walk("Chat.ACME.com."), ["chat.acme.com", "acme.com", "com"])

    def test_un_solo_label_no_se_parte(self):
        self.assertEqual(walk("localhost"), ["localhost"])

    def test_host_vacio_no_produce_sufijos(self):
        self.assertEqual(walk(""), [])


class TestMostSpecificMatch(unittest.TestCase):
    def test_matchea_el_dominio_exacto(self):
        dominios = frozenset({"claude.ai", "openai.com"})
        self.assertEqual(most_specific_match("claude.ai", dominios), "claude.ai")

    def test_un_subdominio_hereda_el_veredicto_del_padre(self):
        dominios = frozenset({"acme.com"})
        self.assertEqual(
            most_specific_match("chat.interno.acme.com", dominios), "acme.com"
        )

    def test_se_queda_con_el_match_mas_especifico_no_el_mas_corto(self):
        # microsoft.com y copilot.microsoft.com pueden vivir en listas
        # distintas y solaparse: el mas especifico tiene que ganar siempre.
        dominios = frozenset({"microsoft.com", "copilot.microsoft.com"})
        self.assertEqual(
            most_specific_match("copilot.microsoft.com", dominios),
            "copilot.microsoft.com",
        )

    def test_sin_match_devuelve_none(self):
        dominios = frozenset({"acme.com"})
        self.assertIsNone(most_specific_match("otraempresa.com", dominios))

    def test_no_matchea_un_sufijo_de_texto_sin_alinear_a_label(self):
        # "malacme.com" no puede matchear "acme.com": el punto de separacion
        # tiene que caer justo en un limite de etiqueta.
        dominios = frozenset({"acme.com"})
        self.assertIsNone(most_specific_match("malacme.com", dominios))

    def test_funciona_igual_sobre_un_dict_que_sobre_un_frozenset(self):
        cache = {"acme.com": {"classification": "ai_unapproved"}}
        self.assertEqual(
            most_specific_match("chat.acme.com", cache), "acme.com"
        )


class TestEscala(unittest.TestCase):
    def test_el_costo_no_crece_con_el_tamano_del_conjunto(self):
        chico = frozenset({f"servicio{i}.com" for i in range(50)} | {"acme.com"})
        grande = frozenset(
            {f"servicio{i}.com" for i in range(50_000)} | {"acme.com"}
        )
        host = "chat.acme.com"

        # Un solo lookup ya alcanza para que el JIT/cache de Python este
        # tibio; lo que importa es que 50000 dominios no tarden ordenes de
        # magnitud mas que 50.
        for _ in range(1000):
            most_specific_match(host, chico)

        inicio = time.perf_counter()
        for _ in range(2000):
            most_specific_match(host, chico)
        tiempo_chico = time.perf_counter() - inicio

        inicio = time.perf_counter()
        for _ in range(2000):
            most_specific_match(host, grande)
        tiempo_grande = time.perf_counter() - inicio

        # Con un barrido O(n) el conjunto de 50000 tardaria ~1000x mas que el
        # de 50. Con la caminata de sufijos deberia ser comparable; se deja
        # margen generoso (10x) para no volver el test fragil por ruido de CI.
        self.assertLess(tiempo_grande, tiempo_chico * 10 + 0.05)


if __name__ == "__main__":
    unittest.main()
