"""El punto de entrada unico y lo que hace falta para que sea un ejecutable.

**Ningun test de aca toca el sistema.** El instalador escribe en el registro,
confia una CA y prende el proxy del navegador: un test que lo haga de verdad le
deja la maquina configurada a quien corra la suite, y si falla en el medio se la
deja a medio configurar. Todo va con dobles.

Lo que se verifica es lo que se rompio o faltaba:

1. Que `instalar` **arranque** el proxy. Antes configuraba el navegador para
   apuntar a 127.0.0.1 y no levantaba nada, o sea que dejaba a la persona SIN
   internet hasta que alguien corriera el proxy a mano. Es la falla del peor tipo
   porque el usuario no puede saber que le falto un paso.
2. Que el estado distinga **configurado** de **protegido**.
3. Que el instalador de produccion no dependa de nada que no exista en un
   paquete: importaba `tests.e2e.harness`, y los tests no se empaquetan.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from aegis_agent import cli, entorno
from aegis_agent.install import windows
from tests.aislamiento import sistema_intocable


class CasoAislado(unittest.TestCase):
    """Base con la red de contencion puesta. TODOS los casos de aca la heredan.

    No es opcional ni "por si acaso": el bug que motivo este archivo fue que un
    test no parcheo lo que creia parchear y corrio el desinstalador de verdad
    contra la maquina del desarrollador. Con esto, equivocarse al parchear ya no
    puede tocar el sistema.
    """

    def setUp(self):
        contexto = sistema_intocable()
        self.sistema = contexto.__enter__()
        self.addCleanup(contexto.__exit__, None, None, None)


class TestNoDependeDeLosTests(CasoAislado):
    """Lo que hacia imposible empaquetar el instalador."""

    def test_el_instalador_no_importa_modulos_de_tests(self):
        """Se mira el ARBOL de sintaxis, no el texto.

        La primera version buscaba la subcadena "from tests" y se disparaba con el
        comentario que explica el bug. Un test que se rompe por su propia
        documentacion no dura.
        """

        import ast
        import pathlib

        arbol = ast.parse(pathlib.Path(windows.__file__).read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            modulo = ""
            if isinstance(nodo, ast.ImportFrom):
                modulo = nodo.module or ""
            elif isinstance(nodo, ast.Import):
                modulo = nodo.names[0].name
            self.assertFalse(
                modulo.split(".")[0] == "tests",
                f"el instalador de produccion importa {modulo}, y los tests "
                "no se empaquetan: en un ejecutable ese import revienta",
            )

    def test_la_ca_se_genera_sin_lanzar_procesos(self):
        """Adentro de un ejecutable no hay ningun mitmdump que lanzar."""

        with patch("subprocess.Popen") as popen, patch.object(
            entorno, "CA_CER"
        ) as ca:
            ca.exists.return_value = True
            self.assertTrue(windows.ensure_ca())
            popen.assert_not_called()

    def test_el_localizador_de_mitmdump_vive_en_produccion(self):
        """Estaba duplicado en el harness y en la demo, y lo usaba el instalador."""

        self.assertTrue(hasattr(entorno, "mitmdump_en_disco"))
        from tests.e2e import harness

        with patch.object(entorno, "mitmdump_en_disco", return_value="X"):
            self.assertEqual(harness.mitmdump_path(), "X")


class TestElPuntoDeEntrada(CasoAislado):
    """El envoltorio no puede tener imports relativos.

    PyInstaller corre su script de entrada como `__main__`, sin paquete padre, asi
    que un `from . import x` revienta con "attempted relative import with no known
    parent package" --y SOLO en el ejecutable. Desde el repo,
    `python -m aegis_agent.cli` funciona perfecto, o sea que el error es invisible
    hasta que alguien abre el paquete.

    Ya paso: el spec apuntaba a `aegis_agent/cli.py` y el .exe compilaba bien y
    fallaba al ejecutarse. Es el mismo error que motivo `aegis_mitm.py` en su
    momento, con otro cargador.
    """

    def test_el_envoltorio_no_usa_imports_relativos(self):
        import ast
        import pathlib

        envoltorio = pathlib.Path(__file__).resolve().parents[1] / "aegis.py"
        self.assertTrue(envoltorio.exists(), "falta el envoltorio del ejecutable")
        arbol = ast.parse(envoltorio.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ImportFrom):
                self.assertEqual(
                    nodo.level,
                    0,
                    "el envoltorio del ejecutable tiene un import relativo: "
                    "PyInstaller lo corre sin paquete padre y va a reventar",
                )

    def test_el_spec_apunta_al_envoltorio(self):
        """Si alguien lo vuelve a apuntar al modulo, el paquete sale roto."""

        import pathlib

        spec = (
            pathlib.Path(__file__).resolve().parents[2] / "packaging" / "aegis.spec"
        )
        if not spec.exists():
            self.skipTest("no hay spec de empaquetado en este arbol")
        texto = spec.read_text(encoding="utf-8")
        self.assertIn('AGENTE / "aegis.py"', texto)
        self.assertNotIn('"aegis_agent" / "cli.py"', texto)


class TestArranqueAutomatico(CasoAislado):
    def test_el_comando_apunta_al_ejecutable_cuando_esta_empaquetado(self):
        with patch.object(entorno, "empaquetado", return_value=True), patch.object(
            sys, "executable", r"C:\Aegis\Aegis.exe"
        ):
            comando = windows.comando_de_arranque(8899)
        self.assertIn("Aegis.exe", comando)
        self.assertIn("servicio", comando)
        self.assertNotIn("-m", comando, "empaquetado no hay modulos que invocar")

    def test_el_comando_usa_el_modulo_cuando_no_esta_empaquetado(self):
        with patch.object(entorno, "empaquetado", return_value=False):
            comando = windows.comando_de_arranque(8899)
        self.assertIn("aegis_agent.cli", comando)
        self.assertIn("servicio", comando)

    def test_las_rutas_con_espacios_van_entre_comillas(self):
        """`C:\\Program Files\\...` sin comillas ejecuta "C:\\Program"."""

        with patch.object(entorno, "empaquetado", return_value=True), patch.object(
            sys, "executable", r"C:\Program Files\Aegis\Aegis.exe"
        ):
            comando = windows.comando_de_arranque(8899)
        self.assertTrue(comando.startswith('"'), comando)

    def test_quitar_el_arranque_es_idempotente(self):
        """Desinstalar tiene que poder correrse dos veces sin quejarse."""

        with patch.object(windows, "_registry") as registro:
            registro.return_value.DeleteValue.side_effect = FileNotFoundError
            self.assertTrue(windows.quitar_arranque())


class TestInstalarArranca(CasoAislado):
    """El agujero que separaba "configurado" de "protegido"."""

    def test_instalar_levanta_el_proxy(self):
        with patch.object(windows, "install", return_value=["configurado"]), patch.object(
            windows, "arranque_registrado", return_value="Aegis.exe servicio"
        ), patch.object(windows, "puerto_escuchando", return_value=False), patch.object(
            cli, "_arrancar_en_segundo_plano", return_value=True
        ) as arrancar:
            cli._instalar(8899)
        arrancar.assert_called_once()

    def test_si_no_puede_arrancar_lo_dice(self):
        """Callarse aca deja a la persona sin internet y sin explicacion."""

        with patch.object(windows, "install", return_value=[]), patch.object(
            windows, "arranque_registrado", return_value="x"
        ), patch.object(windows, "puerto_escuchando", return_value=False), patch.object(
            cli, "_arrancar_en_segundo_plano", return_value=False
        ), patch("builtins.print") as impreso:
            cli._instalar(8899)
        dicho = " ".join(str(c) for c in impreso.call_args_list)
        self.assertIn("No se pudo levantar", dicho)

    def test_no_arranca_dos_veces(self):
        with patch.object(windows, "install", return_value=[]), patch.object(
            windows, "arranque_registrado", return_value="x"
        ), patch.object(windows, "puerto_escuchando", return_value=True), patch.object(
            cli, "_arrancar_en_segundo_plano"
        ) as arrancar:
            cli._instalar(8899)
        arrancar.assert_not_called()

    def test_arrancar_verifica_en_vez_de_suponer(self):
        """Decir "estas protegido" sin comprobarlo es la unica mentira que este
        producto no se puede permitir."""

        with patch("subprocess.Popen"), patch.object(
            windows, "puerto_escuchando", return_value=False
        ), patch("time.time", side_effect=[0, 0, 100]), patch("time.sleep"):
            self.assertFalse(cli._arrancar_en_segundo_plano(8899))


class TestEstadoDiceLaVerdad(CasoAislado):
    BASE = {
        "ca_generada": True,
        "ca_confiada": True,
        "proxy_activo": True,
        "proxy_servidor": "127.0.0.1:8899",
        "apunta_a_aegis": True,
        "excluidos": "",
        "arranca_solo": True,
        "escuchando": True,
    }

    def _decir(self, **cambios) -> tuple[int, str]:
        estado = {**self.BASE, **cambios}
        with patch.object(windows, "status", return_value=estado), patch(
            "builtins.print"
        ) as impreso:
            codigo = cli._estado(8899)
        return codigo, " ".join(str(c) for c in impreso.call_args_list)

    def test_protegido(self):
        codigo, dicho = self._decir()
        self.assertEqual(codigo, 0)
        self.assertIn("esta protegiendo", dicho)

    def test_el_peor_caso_se_avisa_fuerte(self):
        """Navegador apuntando a Aegis + Aegis caido = la persona sin internet.

        Es el unico estado en el que Aegis deja al equipo PEOR que si no
        estuviera, asi que no puede leerse igual que "no esta activo".
        """

        codigo, dicho = self._decir(escuchando=False)
        self.assertEqual(codigo, 1)
        self.assertIn("ATENCION", dicho)
        self.assertIn("sin internet", dicho)

    def test_no_instalado(self):
        codigo, dicho = self._decir(
            apunta_a_aegis=False, escuchando=False, ca_confiada=False
        )
        self.assertEqual(codigo, 1)
        self.assertIn("no esta activo", dicho)

    def test_el_estado_mira_si_hay_alguien_escuchando(self):
        """Sin esto se podia ver todo en verde con el proxy caido."""

        with patch.object(windows, "puerto_escuchando", return_value=True) as sonda, patch.object(
            windows, "arranque_registrado", return_value=""
        ), patch.object(windows, "read_proxy_settings", return_value={
            "enabled": True, "server": "127.0.0.1:8899", "bypass": ""
        }), patch.object(windows, "ca_is_trusted", return_value=True):
            estado = windows.status(8899)
        sonda.assert_called_once_with(8899)
        self.assertIn("escuchando", estado)


class TestElCli(CasoAislado):
    def test_la_ayuda_lista_las_acciones(self):
        with patch("builtins.print") as impreso:
            self.assertEqual(cli.main(["--help"]), 0)
        dicho = " ".join(str(c) for c in impreso.call_args_list)
        for accion in ("instalar", "servicio", "estado", "desinstalar", "verificar"):
            self.assertIn(accion, dicho)

    def test_una_accion_desconocida_no_revienta(self):
        with patch("builtins.print"):
            self.assertEqual(cli.main(["volar"]), 2)

    def test_sin_argumentos_muestra_el_estado(self):
        with patch.object(cli, "_estado", return_value=0) as estado:
            cli.main([])
        estado.assert_called_once()

    def test_acepta_los_nombres_en_ingles(self):
        """El instalador viejo usaba install/uninstall/status y hay documentacion
        y scripts dando vueltas con esos nombres."""

        for viejo, nuevo in (
            ("install", "_instalar"),
            ("uninstall", "_desinstalar"),
            ("status", "_estado"),
        ):
            with self.subTest(accion=viejo):
                with patch.object(cli, nuevo, return_value=0) as fn:
                    cli.main([viejo])
                fn.assert_called_once()

    def test_el_puerto_sale_del_entorno(self):
        with patch.dict(os.environ, {"AEGIS_PORT": "9001"}):
            self.assertEqual(entorno.puerto(), 9001)

    def test_un_puerto_invalido_cae_al_de_siempre(self):
        with patch.dict(os.environ, {"AEGIS_PORT": "no-es-un-numero"}):
            self.assertEqual(entorno.puerto(), entorno.PUERTO_POR_DEFECTO)


class TestElServicio(CasoAislado):
    def test_escucha_solo_en_loopback(self):
        """Un proxy de intercepcion en 0.0.0.0 es un proxy abierto en la oficina:
        cualquiera podria mandarle su trafico para que se lo descifren."""

        from aegis_agent import servicio
        import inspect

        firma = inspect.signature(servicio.correr)
        self.assertEqual(firma.parameters["host"].default, "127.0.0.1")

    def test_no_vuelca_los_flujos(self):
        """Escribir cada request a la consola seria contar por la salida estandar
        justo lo que el ADR 0003 promete que no sale del equipo."""

        from aegis_agent import servicio
        import pathlib

        fuente = pathlib.Path(servicio.__file__).read_text(encoding="utf-8")
        self.assertIn("with_dumper=False", fuente)


if __name__ == "__main__":
    unittest.main()
