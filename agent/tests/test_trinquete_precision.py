"""El trinquete: la precision puede subir, nunca bajar.

Un banco de pruebas que hay que acordarse de correr no protege nada. Este test lo
corre la suite, contra la linea base grabada en `bench/linea_base.json`, y se
pone rojo si un cambio empeora cualquiera de los tres numeros que importan.

## Por que un trinquete y no un umbral fijo

Un umbral fijo ("precision > 95%") se elige una vez, se cumple, y despues deja de
decir nada: se puede perder cuatro puntos y seguir en verde. El trinquete compara
contra lo ultimo que se logro, asi que cada mejora se vuelve el piso nuevo. Es la
diferencia entre una meta y una garantia.

## Como se sube la linea base, cuando corresponde

    cd agent
    python -m bench.precision --guardar

Y el commit que la sube tiene que decir por que subio. Si la linea base baja, el
commit tiene que decir que se cambio a cambio de que: no hay ninguna regla que
prohiba bajarla --a veces se acepta perder precision para ganar cobertura-- pero
tiene que ser una decision escrita y no un descuido.

## Lo que este test NO garantiza

Que el corpus mida el mundo. Los positivos con formato son regresion, no
cobertura (ver `corpus_generado.py`). Lo que este test garantiza es que nadie
rompa en silencio lo que ya funcionaba, que es exactamente el modo de falla que
tuvo este proyecto: la regla de "contrasena" sin enie se veia perfecta en un
corpus escrito sin tildes.
"""

from __future__ import annotations

import json
import unittest

from bench.precision import LINEA_BASE, medir


class TestTrinquete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = json.loads(LINEA_BASE.read_text(encoding="utf-8"))
        cls.ahora = medir()

    def test_la_precision_del_corte_no_baja(self):
        """El numero que decide si el producto sigue instalado."""

        self.assertGreaterEqual(
            self.ahora["precision_del_corte"],
            self.base["precision_del_corte"],
            "la precision del corte bajo. Si fue a proposito, corré "
            "`python -m bench.precision --guardar` y explicá el cambio en el commit.",
        )

    def test_los_falsos_positivos_que_cortan_no_suben(self):
        """El unico falso positivo que cuesta el producto y no solo atencion."""

        self.assertLessEqual(
            self.ahora["tasa_fp_que_corta"],
            self.base["tasa_fp_que_corta"],
            "subieron los falsos positivos que CORTAN un envio legitimo.",
        )

    def test_los_falsos_positivos_totales_no_suben(self):
        self.assertLessEqual(
            self.ahora["tasa_fp_total"],
            self.base["tasa_fp_total"],
            "subio el ruido en el panel.",
        )

    def test_el_recall_no_baja_en_ninguna_familia(self):
        """Por familia y no en total, porque un promedio esconde el hueco.

        Perder todos los documentos de identidad y ganar unos secretos deja el
        promedio igual y el producto peor.
        """

        for familia, esperado in self.base["recall"].items():
            with self.subTest(familia=familia):
                actual = self.ahora["familias"].get(familia)
                self.assertIsNotNone(
                    actual, f"la familia '{familia}' desaparecio del banco"
                )
                self.assertGreaterEqual(
                    actual["detectados"] / actual["total"],
                    esperado["detectados"] / esperado["total"],
                    f"bajo el recall de {familia}",
                )

    def test_el_corpus_no_se_encogio(self):
        """Un corpus mas chico sube todos los numeros sin mejorar nada.

        Es la forma mas facil de poner el trinquete en verde haciendo trampa, y
        por eso se mide aparte.
        """

        self.assertGreaterEqual(
            self.ahora["casos"],
            self.base["casos"],
            "el corpus se encogio: los numeros de arriba no son comparables.",
        )

    def test_el_corpus_es_determinista(self):
        """Dos corridas, el mismo resultado.

        Un trinquete sobre un corpus que cambia entre corridas es un test
        intermitente, y un test intermitente se termina borrando.
        """

        otra = medir()
        self.assertEqual(
            otra["precision_del_corte"], self.ahora["precision_del_corte"]
        )
        self.assertEqual(otra["casos"], self.ahora["casos"])


if __name__ == "__main__":
    unittest.main()
