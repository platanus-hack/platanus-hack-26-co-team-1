"""Cerrar la capa D: lo que se hace con un punto ciego cuando la empresa
elige cortar en vez de solo mirarlo.

Los tests no tocan el firewall de verdad: verifican que los comandos que se
arman sean los correctos. Una suite que reconfigura la red de quien la corre no
la corre nadie dos veces.
"""

import unittest
from unittest import mock

from aegis_agent.install import firewall

IPS = ["203.0.113.7", "203.0.113.8", "203.0.113.7"]
PROGRAMA = r"C:\Users\alguien\AppData\Local\Programs\chatgpt\chatgpt.exe"


class TestComandos(unittest.TestCase):
    def _capturar(self):
        llamadas = []

        def falso(argumentos):
            llamadas.append(argumentos)
            return True, ""

        parche = mock.patch.object(firewall, "_netsh", falso)
        parche.start()
        self.addCleanup(parche.stop)
        return llamadas

    def test_el_bloqueo_por_programa_no_alcanza_a_los_demas(self):
        """En Windows el bloqueo le gana al permiso.

        Por eso no se puede bloquear todo y dejar pasar al proxy: la regla lo
        alcanzaria tambien y Aegis se cortaria a si mismo. Se bloquea el
        programa que se estaba saltando el proxy y nada mas.
        """

        llamadas = self._capturar()
        firewall.bloquear_programa(PROGRAMA, IPS)
        argumentos = llamadas[0]
        self.assertIn(f"program={PROGRAMA}", argumentos)
        self.assertIn("action=block", argumentos)
        self.assertIn("protocol=TCP", argumentos)
        self.assertIn("dir=out", argumentos)

    def test_quic_se_bloquea_para_todos_y_eso_esta_bien(self):
        """mitmproxy habla TCP: bloquear UDP 443 no lo toca y devuelve el
        trafico al camino donde Aegis si escucha."""

        llamadas = self._capturar()
        firewall.bloquear_quic(IPS)
        argumentos = llamadas[0]
        self.assertIn("protocol=UDP", argumentos)
        self.assertIn("remoteport=443", argumentos)
        self.assertFalse([a for a in argumentos if a.startswith("program=")])

    def test_las_ips_repetidas_no_se_duplican(self):
        llamadas = self._capturar()
        firewall.bloquear_quic(IPS)
        remoteip = [a for a in llamadas[0] if a.startswith("remoteip=")][0]
        self.assertEqual(remoteip, "remoteip=203.0.113.7,203.0.113.8")

    def test_todo_queda_en_el_grupo_de_aegis(self):
        """Sin un grupo comun, revertir significaria adivinar que reglas eran nuestras."""

        llamadas = self._capturar()
        firewall.bloquear_quic(IPS)
        firewall.bloquear_programa(PROGRAMA, IPS)
        for argumentos in llamadas:
            self.assertIn(f"group={firewall.GRUPO}", argumentos)

    def test_revertir_borra_por_grupo_y_no_una_por_una(self):
        llamadas = self._capturar()
        firewall.revertir()
        self.assertEqual(
            llamadas[0], ["delete", "rule", f"group={firewall.GRUPO}"]
        )


class TestPlan(unittest.TestCase):
    def test_el_plan_se_puede_leer_antes_de_tocar_nada(self):
        pasos = firewall.plan([PROGRAMA], IPS)
        self.assertTrue(pasos)
        self.assertTrue(all(p.description and p.detail for p in pasos))
        self.assertIn("chatgpt.exe", " ".join(p.description for p in pasos))

    def test_el_plan_avisa_que_es_reversible(self):
        texto = " ".join(p.detail for p in firewall.plan([PROGRAMA], IPS))
        self.assertIn("revertir", texto.lower())


class TestErrores(unittest.TestCase):
    def test_si_netsh_no_esta_no_se_cae(self):
        with mock.patch.object(
            firewall.subprocess, "run", side_effect=OSError("no existe netsh")
        ):
            ok, detalle = firewall.revertir()
        self.assertFalse(ok)
        self.assertIn("netsh", detalle)


if __name__ == "__main__":
    unittest.main()
