"""T2 tenia presupuesto de latencia y T1 no, y el que se pasaba era T1.

Medido en la auditoria del 22-ago-2026: 28 reglas sobre un cuerpo grande cuestan
del orden de 1 ms por KB, o sea ~100 ms en 256 KB y cerca de un SEGUNDO en 1 MB.
La documentacion decia "~0.2 ms" y es cierto --sobre un prompt corto. El caso que
importa no es el prompt corto: es el pegado de un documento.

La regla que ya estaba escrita en el repo, y que este archivo extiende al nivel
que la incumplia: **un escaneo lento no puede frenar a la persona.**

## Lo que estos tests protegen, en orden de importancia

1. Que el secreto de la COLA se siga encontrando. Es lo primero porque es lo que
   se podia romper al acotar: recorrer de principio a fin y cortar por tiempo
   habria dejado afuera justo el final, que es donde el propio repo ya documento
   que se esconde el secreto.
2. Que la latencia quede acotada de verdad.
3. Que un escaneo incompleto se REPORTE. Uno incompleto en silencio es una
   promesa que el producto no esta cumpliendo.
"""

from __future__ import annotations

import importlib
import json
import time
import unittest
from unittest.mock import patch

from aegis_agent.detect import payload as P

LLAVE = "AKIAIOSFODNN7EXAMPLE"


def cuerpo(kb: int, cola: str = "", cabeza: str = "") -> bytes:
    relleno = "dato de relleno " * (kb * 64)
    return json.dumps(
        {"messages": [{"role": "user", "content": f"{cabeza} {relleno} {cola}"}]}
    ).encode()


class TestLaColaNoSePierde(unittest.TestCase):
    """El caso que decidio el orden de los segmentos."""

    def test_el_secreto_al_final_de_un_cuerpo_enorme(self):
        for kb in (64, 512, 2048, 8192):
            with self.subTest(kb=kb):
                resultado = P.scan_payload(cuerpo(kb, cola=f"y la llave es {LLAVE}"))
                self.assertIn(
                    "aws_access_key_id",
                    {f.rule_id for f in resultado.findings},
                    f"se perdio el secreto de la cola con {kb} KB",
                )

    def test_el_secreto_al_principio_tambien(self):
        resultado = P.scan_payload(cuerpo(4096, cabeza=f"la llave es {LLAVE}"))
        self.assertIn("aws_access_key_id", {f.rule_id for f in resultado.findings})

    def test_los_dos_a_la_vez_son_un_solo_incidente_por_regla(self):
        resultado = P.scan_payload(
            cuerpo(1024, cabeza=f"llave {LLAVE}", cola=f"llave {LLAVE}")
        )
        self.assertIn("aws_access_key_id", {f.rule_id for f in resultado.findings})


class TestElSolape(unittest.TestCase):
    """Un hallazgo que cruza el corte entre dos segmentos no puede perderse."""

    def test_secreto_justo_en_el_borde_del_segmento(self):
        # Se lo pone a caballo del corte, corriendolo unos caracteres por vez.
        for desfase in (-8, -4, -1, 0, 1, 4, 8):
            with self.subTest(desfase=desfase):
                relleno = "x" * (P.SEGMENTO + desfase)
                crudo = json.dumps(
                    {"messages": [{"content": relleno + f" la llave es {LLAVE} " + "y" * 2000}]}
                ).encode()
                self.assertIn(
                    "aws_access_key_id",
                    {f.rule_id for f in P.scan_payload(crudo).findings},
                    f"se perdio en el borde con desfase {desfase}",
                )

    def test_el_solape_no_duplica_el_hallazgo(self):
        """La zona de solape se mira dos veces y el incidente es uno.

        Las posiciones de los hallazgos se corrigen por el desplazamiento del
        segmento justamente para esto: con posiciones relativas, el mismo secreto
        visto en los dos lados del solape se reportaba dos veces.
        """

        relleno = "x" * (P.SEGMENTO - 200)
        crudo = json.dumps(
            {"messages": [{"content": relleno + f" la llave es {LLAVE} " + "y" * 4000}]}
        ).encode()
        hallazgos = [
            f for f in P.scan_payload(crudo).findings if f.rule_id == "aws_access_key_id"
        ]
        self.assertEqual(len(hallazgos), 1, "el solape duplico el incidente")


class TestElPresupuestoAcota(unittest.TestCase):
    def test_un_cuerpo_enorme_no_tarda_proporcionalmente(self):
        """Lo que se protege: que 8 MB no cuesten ocho veces lo que 1 MB."""

        inicio = time.perf_counter()
        P.scan_payload(cuerpo(8192))
        transcurrido = (time.perf_counter() - inicio) * 1000
        # El presupuesto se mira ENTRE segmentos, asi que el exceso esta acotado
        # por lo que cuesta un segmento. Se deja margen generoso porque en una
        # maquina cargada la misma medicion vario entre 400 y 2.700 ms, y un test
        # de tiempo apretado es un test intermitente.
        self.assertLess(
            transcurrido,
            P.PRESUPUESTO_MS * 6,
            f"el presupuesto no acoto nada: {transcurrido:.0f} ms",
        )

    def test_avisa_cuando_quedo_incompleto(self):
        self.assertTrue(P.scan_payload(cuerpo(8192)).truncated)

    def test_un_cuerpo_normal_no_se_marca_truncado(self):
        """Un prompt de tamano corriente tiene que salir completo y rapido."""

        resultado = P.scan_payload(cuerpo(4, cola=f"la llave es {LLAVE}"))
        self.assertFalse(resultado.truncated)
        self.assertIn("aws_access_key_id", {f.rule_id for f in resultado.findings})

    def test_con_presupuesto_apretado_sigue_viendo_la_cola(self):
        """Lo mas importante de todo el archivo.

        Con el presupuesto casi agotado, lo que se mira es cabeza y cola. Si esto
        se pone rojo, alguien cambio el orden de los segmentos y el secreto del
        final volvio a ser invisible.
        """

        with patch.object(P, "PRESUPUESTO_MS", 1):
            resultado = P.scan_payload(cuerpo(4096, cola=f"y la llave es {LLAVE}"))
        self.assertIn("aws_access_key_id", {f.rule_id for f in resultado.findings})
        self.assertTrue(resultado.truncated)


class TestConfigurable(unittest.TestCase):
    def test_se_puede_cambiar_por_entorno(self):
        with patch.dict("os.environ", {"AEGIS_T1_PRESUPUESTO_MS": "1234"}):
            recargado = importlib.reload(P)
            self.assertEqual(recargado.PRESUPUESTO_MS, 1234)
        importlib.reload(P)

    def test_los_segmentos_cubren_todo_el_texto(self):
        """Ningun pedazo del texto puede quedar sin visitar."""

        texto = "".join(str(i % 10) for i in range(P.SEGMENTO * 3 + 777))
        cubierto = bytearray(len(texto))
        for pedazo, desplazamiento in P._segmentos(texto):
            self.assertEqual(texto[desplazamiento : desplazamiento + len(pedazo)], pedazo)
            for i in range(desplazamiento, desplazamiento + len(pedazo)):
                cubierto[i] = 1
        self.assertEqual(sum(cubierto), len(texto), "quedo texto sin visitar")

    def test_un_texto_chico_es_un_solo_segmento(self):
        self.assertEqual(list(P._segmentos("hola")), [("hola", 0)])

    def test_el_segundo_segmento_es_la_cola(self):
        texto = "a" * (P.SEGMENTO * 4)
        segmentos = list(P._segmentos(texto))
        _, desplazamiento_cola = segmentos[1]
        self.assertGreater(
            desplazamiento_cola + P.SEGMENTO,
            len(texto) - 1,
            "el segundo segmento tiene que llegar hasta el final del texto",
        )


if __name__ == "__main__":
    unittest.main()
