"""La regla de tarjeta inventaba datos personales en envíos con muchos números.

Se encontró en tráfico real. El panel mostraba, sobre un sitio que no es una IA,
cinco hallazgos de `credit_card` y un `bulk_pii_export` de dieciséis datos
personales. No había ninguna tarjeta: era un envío grande con datos numéricos.

Dos causas, las dos medidas:

1. **El patrón admitía un separador entre CADA dígito**, así que un candidato
   podía cruzar varios números distintos: "120-455 803-217 964-330 1" se lee
   como una tirada de trece dígitos. Una tarjeta se agrupa de a cuatro (o 4-6-5
   si es Amex) y nunca dígito por dígito.

2. **Luhn sola no alcanza.** Descarta nueve de cada diez candidatos, así que en
   texto corto no se nota nunca; en un envío de 671 KB con números hay decenas
   de miles de candidatos y el décimo aparece igual. Lo que separa una tarjeta
   de una tirada cualquiera es el prefijo del emisor.

Medido sobre las mismas muestras, coincidencias que pasaban la validación:

        muestra              antes    después
        array de números       910        187
        coordenadas svg        650          0
        timestamps ms        1.971        230

De 3.531 a 417. No es cero y no puede serlo: dieciséis dígitos que empiezan con
4 y pasan Luhn son indistinguibles de una Visa mirando sólo el contenido. Lo que
sí se puede es no perder ninguna tarjeta de verdad, y eso es la mitad de abajo.
"""

from __future__ import annotations

import random
import re
import unittest

from aegis_agent.detect.engine import scan
from aegis_agent.detect.entropy import es_tarjeta, luhn_valid

# Números de prueba públicos de cada red. Ninguno corresponde a una cuenta real:
# son los que publican los propios emisores para probar integraciones.
TARJETAS = (
    "4111111111111111",
    "4111 1111 1111 1111",
    "4111-1111-1111-1111",
    "4012 8888 8888 1881",
    "5500 0000 0000 0004",
    "2223 0000 4841 0010",
    "378282246310005",
    "3782 822463 10005",
    "6011 1111 1111 1117",
)


class TestNoPierdeNingunaTarjeta(unittest.TestCase):
    """La mitad que importa: apretar la regla no puede costar cobertura."""

    def test_las_redes_que_existen_se_siguen_viendo(self):
        for numero in TARJETAS:
            with self.subTest(numero=numero):
                self.assertIn(
                    "credit_card",
                    {f.rule_id for f in scan(numero)},
                    f"se perdio una tarjeta valida: {numero}",
                )

    def test_pegada_y_separada_dan_lo_mismo(self):
        self.assertEqual(
            {f.rule_id for f in scan("4111111111111111")},
            {f.rule_id for f in scan("4111 1111 1111 1111")},
        )


class TestNoInventaTarjetas(unittest.TestCase):
    def test_un_timestamp_no_es_una_tarjeta(self):
        """Trece digitos que pasan Luhn, pero nadie emite tarjetas que empiecen con 1."""

        candidato = "1712345678907"
        self.assertTrue(luhn_valid(candidato), "el caso perdio su gracia")
        self.assertFalse(es_tarjeta(candidato))

    def test_el_separador_no_puede_ir_entre_cada_digito(self):
        """Era lo que dejaba que un candidato cruzara varios numeros distintos."""

        self.assertEqual(scan("valores 4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1"), [])

    def test_las_coordenadas_no_producen_tarjetas(self):
        random.seed(7)
        coordenadas = " ".join(
            f"{random.randint(0, 999)}-{random.randint(0, 999)}" for _ in range(20000)
        )
        patron = re.compile(
            r"\b(?:\d{13,19}"
            r"|\d{4}(?:[ -]\d{4}){2}[ -]\d{1,7}"
            r"|\d{4}[ -]\d{6}[ -]\d{5})\b"
        )
        self.assertEqual(
            sum(1 for m in patron.finditer(coordenadas) if es_tarjeta(m.group())),
            0,
        )

    def test_el_ruido_numerico_cae_al_menos_un_ochenta_por_ciento(self):
        """El numero exacto va a moverse; que no vuelva a subir es lo que se cuida."""

        random.seed(7)
        numeros = " ".join(str(random.randint(0, 9999)) for _ in range(40000))
        viejo = re.compile(r"\b(?:\d[ -]?){13,19}\b")
        nuevo = re.compile(
            r"\b(?:\d{13,19}"
            r"|\d{4}(?:[ -]\d{4}){2}[ -]\d{1,7}"
            r"|\d{4}[ -]\d{6}[ -]\d{5})\b"
        )
        antes = sum(1 for m in viejo.finditer(numeros) if luhn_valid(m.group()))
        despues = sum(1 for m in nuevo.finditer(numeros) if es_tarjeta(m.group()))
        # Medido: 910 -> 187, o sea 0.205. El umbral deja margen para que el
        # numero se mueva sin volver al test una alarma de ruido, y sigue
        # fallando si alguien afloja la regla de verdad.
        self.assertLess(despues, antes * 0.3, f"antes {antes}, despues {despues}")

    def test_el_texto_de_trabajo_normal_sigue_limpio(self):
        self.assertEqual(
            scan("Reunion el martes, revisar el roadmap del Q3 y el presupuesto."),
            [],
        )


if __name__ == "__main__":
    unittest.main()
