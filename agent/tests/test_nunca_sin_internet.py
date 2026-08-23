"""El invariante: Aegis nunca puede dejar a alguien sin internet.

    ProxyEnable=1 apuntando a 127.0.0.1:8899   y nadie escuchando ahi

Ese es el unico estado en el que Aegis deja el equipo PEOR que si no estuviera
instalado, y ocurrio de verdad: el proxy se murio a mitad de sesion y quien lo
tenia instalado se quedo sin red, sin ninguna pista de por que.

No se arregla con cuidado. Se arregla con tres mecanismos, y este archivo prueba
los tres:

1. **El orden.** El proxy se enruta DESPUES de confirmar que hay alguien
   escuchando. Asi el estado malo no existe ni por un instante, ni siquiera si
   algo falla en el medio.
2. **El guardian.** Un proceso APARTE que apaga el proxy si el servicio muere.
   Aparte porque el caso a cubrir es justamente que el servicio muera: un hilo
   adentro del proxy se muere con el proxy.
3. **El reconciliador.** Corre en cada invocacion del CLI y arregla el estado malo
   si ya ocurrio. Cubre el caso en que mataron a los dos, o en que la maquina se
   apago de golpe.

Ningun test de aca toca el sistema: todos heredan la red de contencion.
"""

from __future__ import annotations

import unittest
from unittest.mock import call, patch

from aegis_agent import cli, guardian
from aegis_agent.install import windows
from tests.aislamiento import sistema_intocable


class CasoAislado(unittest.TestCase):
    def setUp(self):
        contexto = sistema_intocable()
        self.sistema = contexto.__enter__()
        self.addCleanup(contexto.__exit__, None, None, None)


class TestElOrden(CasoAislado):
    """Lo primero, porque es lo que hace que el estado malo no exista."""

    def test_no_se_enruta_si_nadie_escucha(self):
        with patch.object(windows, "puerto_escuchando", return_value=False), patch.object(
            windows, "write_proxy_settings"
        ) as escribir:
            enrutado, detalle = windows.enrutar(8899)
        self.assertFalse(enrutado)
        escribir.assert_not_called()
        self.assertIn("sin internet", detalle)

    def test_no_se_enruta_si_la_ca_no_esta_confiada(self):
        with patch.object(windows, "puerto_escuchando", return_value=True), patch.object(
            windows, "ca_is_trusted", return_value=False
        ), patch.object(windows, "write_proxy_settings") as escribir:
            enrutado, _ = windows.enrutar(8899)
        self.assertFalse(enrutado)
        escribir.assert_not_called()

    def test_se_enruta_solo_con_las_dos_condiciones(self):
        with patch.object(windows, "puerto_escuchando", return_value=True), patch.object(
            windows, "ca_is_trusted", return_value=True
        ), patch.object(windows, "write_proxy_settings") as escribir:
            enrutado, _ = windows.enrutar(8899)
        self.assertTrue(enrutado)
        escribir.assert_called_once()

    def test_install_no_prende_el_proxy_por_su_cuenta(self):
        """El bug original: install() enrutaba antes de que existiera el servicio."""

        with patch.object(windows, "ensure_ca", return_value=True), patch.object(
            windows, "trust_ca", return_value=True
        ), patch.object(windows, "ca_is_trusted", return_value=True), patch.object(
            windows, "set_env_vars"
        ), patch.object(
            windows, "registrar_arranque", return_value=True
        ), patch.object(
            windows, "write_proxy_settings"
        ) as escribir:
            windows.install(8899)
        escribir.assert_not_called()

    def test_si_no_arranca_no_se_toca_el_proxy(self):
        """El caso que dejaba a la persona sin red: arrancar falla."""

        with patch.object(windows, "install", return_value=[]), patch.object(
            windows, "puerto_escuchando", return_value=False
        ), patch.object(
            cli, "_arrancar_en_segundo_plano", return_value=False
        ), patch.object(windows, "enrutar") as enrutar, patch("builtins.print") as dicho:
            codigo = cli._instalar(8899)
        enrutar.assert_not_called()
        self.assertEqual(codigo, 1)
        salida = " ".join(str(c) for c in dicho.call_args_list)
        self.assertIn("Tu red esta intacta", salida)

    def test_enrutar_va_despues_de_arrancar(self):
        """No alcanza con que las dos cosas pasen: importa el orden."""

        orden = []
        with patch.object(windows, "install", return_value=[]), patch.object(
            windows, "puerto_escuchando", return_value=False
        ), patch.object(
            cli,
            "_arrancar_en_segundo_plano",
            side_effect=lambda p: orden.append("arrancar") or True,
        ), patch.object(
            windows,
            "enrutar",
            side_effect=lambda p: orden.append("enrutar") or (False, ""),
        ), patch("builtins.print"):
            cli._instalar(8899)
        self.assertEqual(orden, ["arrancar", "enrutar"])


class TestElGuardian(CasoAislado):
    def test_actua_solo_si_el_proxy_apunta_a_aegis(self):
        """Sin esto apagaria un proxy que la persona configuro hacia otra cosa."""

        with patch.object(
            windows, "read_proxy_settings",
            return_value={"enabled": True, "server": "10.0.0.1:3128", "bypass": ""},
        ):
            self.assertFalse(guardian.hay_que_actuar(8899))

        with patch.object(
            windows, "read_proxy_settings",
            return_value={"enabled": True, "server": "127.0.0.1:8899", "bypass": ""},
        ):
            self.assertTrue(guardian.hay_que_actuar(8899))

    def test_no_actua_si_el_proxy_esta_apagado(self):
        with patch.object(
            windows, "read_proxy_settings",
            return_value={"enabled": False, "server": "127.0.0.1:8899", "bypass": ""},
        ):
            self.assertFalse(guardian.hay_que_actuar(8899))

    def test_aguanta_una_caida_corta_sin_apagar_nada(self):
        """Reiniciar el servicio tarda un momento y no es una emergencia.

        Apagar el proxy por eso seria una falsa alarma que desprotege a la
        persona sin motivo.
        """

        respuestas = [False] * (guardian.FALLAS_PARA_ACTUAR - 1) + [True]
        with patch.object(guardian, "_escucha", side_effect=respuestas), patch.object(
            guardian, "apagar_el_proxy"
        ) as apagar, patch("time.sleep"), patch.object(
            guardian, "hay_que_actuar", return_value=True
        ):
            # Se corta el bucle cuando se agotan las respuestas.
            with self.assertRaises(StopIteration):
                guardian.vigilar(8899)
        apagar.assert_not_called()

    def test_apaga_el_proxy_si_el_servicio_no_vuelve(self):
        with patch.object(guardian, "_escucha", return_value=False), patch.object(
            guardian, "hay_que_actuar", return_value=True
        ), patch.object(guardian, "apagar_el_proxy", return_value=True) as apagar, patch(
            "time.sleep"
        ):
            self.assertEqual(guardian.vigilar(8899), 0)
        apagar.assert_called_once()

    def test_no_toca_la_ca_ni_las_variables(self):
        """Quitar la CA abre un dialogo de Windows, y es lo ultimo que quiere ver
        alguien que en ese momento no tiene internet."""

        with patch.object(windows, "write_proxy_settings") as escribir, patch.object(
            windows, "untrust_ca"
        ) as ca, patch.object(windows, "clear_env_vars") as variables:
            guardian.apagar_el_proxy()
        escribir.assert_called_once_with(False)
        ca.assert_not_called()
        variables.assert_not_called()

    def test_se_lanza_desprendido(self):
        """Tiene que sobrevivir a la muerte del servicio, que es su unico motivo."""

        with patch("subprocess.Popen") as popen:
            guardian.lanzar(8899)
        banderas = popen.call_args.kwargs.get("creationflags", 0)
        import subprocess as sp

        self.assertTrue(banderas & getattr(sp, "DETACHED_PROCESS", 0))


class TestElReconciliador(CasoAislado):
    def test_arregla_el_estado_malo_y_lo_dice(self):
        """Un arreglo silencioso deja a la persona sin entender que paso."""

        with patch.object(guardian, "_escucha", return_value=False), patch.object(
            guardian, "hay_que_actuar", return_value=True
        ), patch.object(guardian, "apagar_el_proxy", return_value=True):
            aviso = guardian.reconciliar(8899)
        self.assertIn("sin internet", aviso)

    def test_calla_si_todo_esta_bien(self):
        with patch.object(guardian, "_escucha", return_value=True):
            self.assertEqual(guardian.reconciliar(8899), "")

    def test_avisa_fuerte_si_no_pudo_arreglarlo(self):
        with patch.object(guardian, "_escucha", return_value=False), patch.object(
            guardian, "hay_que_actuar", return_value=True
        ), patch.object(guardian, "apagar_el_proxy", return_value=False):
            aviso = guardian.reconciliar(8899)
        self.assertIn("ATENCION", aviso)

    def test_corre_en_cada_accion_del_cli(self):
        """La persona que se quedo sin internet va a escribir cualquier cosa, no
        la correcta. Asi que cualquier cosa lo arregla."""

        for accion in ("estado", "plan", "verificar", "desinstalar"):
            with self.subTest(accion=accion):
                with patch.object(
                    guardian, "reconciliar", return_value=""
                ) as reconciliar, patch.object(
                    cli, cli.ACCIONES[accion], return_value=0
                ), patch("builtins.print"):
                    cli.main([accion])
                reconciliar.assert_called_once()

    def test_NO_corre_en_servicio(self):
        """El servicio esta arrancando: el puerto todavia no escucha, y reconciliar
        ahi apagaria el proxy justo cuando esta por levantarse."""

        with patch.object(guardian, "reconciliar") as reconciliar, patch.object(
            cli, "_servicio", return_value=0
        ):
            cli.main(["servicio"])
        reconciliar.assert_not_called()


class TestElServicioLlevaSuGuardian(CasoAislado):
    def test_el_arranque_automatico_tambien_tiene_red_de_contencion(self):
        """Despues de reiniciar la maquina, el autostart corre `servicio` directo.

        Sin lanzar el guardian ahi, el proxy quedaria sin proteccion desde el
        primer reinicio.
        """

        with patch.object(cli, "windows_apunta_a_aegis", return_value=True), patch.object(
            guardian, "lanzar"
        ) as lanzar, patch("aegis_agent.servicio.correr", return_value=0):
            cli._servicio(8899)
        lanzar.assert_called_once_with(8899)

    def test_sin_proxy_configurado_no_hace_falta_guardian(self):
        with patch.object(cli, "windows_apunta_a_aegis", return_value=False), patch.object(
            guardian, "lanzar"
        ) as lanzar, patch("aegis_agent.servicio.correr", return_value=0):
            cli._servicio(8899)
        lanzar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
