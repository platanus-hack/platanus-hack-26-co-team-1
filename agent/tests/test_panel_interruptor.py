"""El interruptor del panel local, y el ataque que tiene que resistir.

Hasta acá las únicas dos posiciones eran "instalado" y "desinstalado", y
desinstalar borra la CA del almacén de Windows, saca las variables y quita el
arranque. Para dejar de interceptar un rato -- probar si una app se rompe por
culpa de Aegis, mostrar el antes y el después -- eso es demoler la casa para
apagar la luz.

**La mitad de abajo es la que importa de verdad.** Un endpoint que apaga un DLP,
escuchando en 127.0.0.1 y sin autenticar, lo puede apretar cualquier página que
la persona tenga abierta en otra pestaña: un formulario apuntado a
`http://127.0.0.1:8787/api/proteccion` se manda solo y el navegador lo entrega.
Apagar la herramienta de seguridad desde una web sería el peor agujero que este
producto podría tener, así que se prueba que no se pueda.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from aegis_agent import control
from aegis_agent.panel import server as panel

TOKEN = "token-de-prueba-abc123"


class PanelLevantado(unittest.TestCase):
    """Un panel de verdad en un puerto libre, con el control simulado."""

    def setUp(self):
        self.workdir = TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        cola = Path(self.workdir.name) / "eventos.jsonl"
        cola.write_text("", encoding="utf-8")

        self.servidor = panel.serve(cola, 0, token=TOKEN)
        self.addCleanup(self.servidor.server_close)
        self.puerto = self.servidor.server_address[1]
        hilo = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        hilo.start()
        self.addCleanup(self.servidor.shutdown)

    def _pedir(self, camino, metodo="GET", cabeceras=None, cuerpo=None):
        peticion = urllib.request.Request(
            f"http://127.0.0.1:{self.puerto}{camino}",
            method=metodo,
            data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            headers=cabeceras or {},
        )
        try:
            with urllib.request.urlopen(peticion, timeout=5) as respuesta:
                return respuesta.status, respuesta.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")


class TestNadieMasPuedeApagarlo(PanelLevantado):
    """El agujero que este diseño existe para tapar."""

    def test_sin_token_no_se_apaga(self):
        with patch.object(control, "apagar") as apagar:
            codigo, _ = self._pedir(
                "/api/proteccion", "POST", cuerpo={"accion": "apagar"}
            )
        self.assertEqual(codigo, 403)
        apagar.assert_not_called()

    def test_con_un_token_inventado_tampoco(self):
        with patch.object(control, "apagar") as apagar:
            codigo, _ = self._pedir(
                "/api/proteccion",
                "POST",
                cabeceras={"X-Aegis-Token": "me-lo-invente"},
                cuerpo={"accion": "apagar"},
            )
        self.assertEqual(codigo, 403)
        apagar.assert_not_called()

    def test_otra_pagina_con_el_token_correcto_tampoco(self):
        """Si el token se filtrara igual, el Origin ajeno lo frena."""

        with patch.object(control, "apagar") as apagar:
            codigo, _ = self._pedir(
                "/api/proteccion",
                "POST",
                cabeceras={
                    "X-Aegis-Token": TOKEN,
                    "Origin": "https://sitio-cualquiera.example",
                },
                cuerpo={"accion": "apagar"},
            )
        self.assertEqual(codigo, 403)
        apagar.assert_not_called()

    def test_el_rechazo_no_explica_que_falto(self):
        """A quien no deberia estar preguntando no se le da el mapa."""

        _, cuerpo = self._pedir("/api/proteccion", "POST", cuerpo={"accion": "apagar"})
        self.assertNotIn("token", cuerpo.lower())

    def test_el_panel_no_se_puede_embeber(self):
        """Sin esto se lo pone en un iframe invisible y se le roba el clic."""

        peticion = urllib.request.Request(f"http://127.0.0.1:{self.puerto}/")
        with urllib.request.urlopen(peticion, timeout=5) as respuesta:
            self.assertEqual(respuesta.headers.get("X-Frame-Options"), "DENY")


class TestElInterruptorFunciona(PanelLevantado):
    def test_con_el_token_del_panel_si_apaga(self):
        with patch.object(control, "apagar", return_value=(True, "apagado")) as apagar:
            codigo, cuerpo = self._pedir(
                "/api/proteccion",
                "POST",
                cabeceras={"X-Aegis-Token": TOKEN},
                cuerpo={"accion": "apagar"},
            )
        self.assertEqual(codigo, 200)
        apagar.assert_called_once()
        self.assertTrue(json.loads(cuerpo)["ok"])

    def test_prender_y_apagar_son_acciones_distintas(self):
        with patch.object(control, "prender", return_value=(True, "ok")) as prender:
            self._pedir(
                "/api/proteccion",
                "POST",
                cabeceras={"X-Aegis-Token": TOKEN},
                cuerpo={"accion": "prender"},
            )
        prender.assert_called_once()

    def test_un_fallo_del_control_llega_como_fallo(self):
        """Si no se pudo, la pantalla tiene que poder decirlo."""

        with patch.object(control, "prender", return_value=(False, "no se pudo")):
            _, cuerpo = self._pedir(
                "/api/proteccion",
                "POST",
                cabeceras={"X-Aegis-Token": TOKEN},
                cuerpo={"accion": "prender"},
            )
        datos = json.loads(cuerpo)
        self.assertFalse(datos["ok"])
        self.assertIn("no se pudo", datos["mensaje"])

    def test_el_estado_se_puede_consultar_sin_token(self):
        """Leer no cambia nada: solo escribir necesita permiso."""

        codigo, cuerpo = self._pedir("/api/estado")
        self.assertEqual(codigo, 200)
        self.assertIn("situacion", json.loads(cuerpo))


class TestElControl(unittest.TestCase):
    """La logica, sin servidor de por medio."""

    def _con_estado(self, **campos):
        base = {
            "situacion": control.APAGADO,
            "puerto": 8899,
            "escuchando": False,
            "ruteado": False,
            "instalado": True,
            "ca_confiada": True,
            "arranca_solo": True,
        }
        base.update(campos)
        return patch.object(control, "estado", return_value=base)

    def test_prender_sin_instalar_no_toca_el_proxy(self):
        """El estado peligroso no se puede alcanzar ni queriendo."""

        from aegis_agent.install import windows

        with self._con_estado(instalado=False, situacion=control.SIN_INSTALAR), \
             patch.object(windows, "enrutar") as enrutar:
            ok, mensaje = control.prender(8899)
        self.assertFalse(ok)
        enrutar.assert_not_called()
        self.assertIn("instalar", mensaje)

    def test_prender_sin_nadie_escuchando_levanta_el_servicio_primero(self):
        from aegis_agent.install import windows

        with self._con_estado(escuchando=False), \
             patch("aegis_agent.cli._arrancar_en_segundo_plano", return_value=True) as arrancar, \
             patch.object(windows, "enrutar", return_value=(True, "ok")) as enrutar:
            control.prender(8899)
        arrancar.assert_called_once()
        enrutar.assert_called_once()

    def test_si_el_servicio_no_arranca_NO_se_rutea(self):
        """Rutear a un puerto muerto es dejar a la persona sin internet."""

        from aegis_agent.install import windows

        with self._con_estado(escuchando=False), \
             patch("aegis_agent.cli._arrancar_en_segundo_plano", return_value=False), \
             patch.object(windows, "enrutar") as enrutar:
            ok, mensaje = control.prender(8899)
        self.assertFalse(ok)
        enrutar.assert_not_called()
        self.assertIn("internet", mensaje)

    def test_apagar_no_desinstala_nada(self):
        from aegis_agent.install import windows

        with self._con_estado(ruteado=True, escuchando=True), \
             patch.object(windows, "write_proxy_settings") as escribir, \
             patch.object(windows, "untrust_ca") as untrust, \
             patch.object(windows, "clear_env_vars") as limpiar:
            ok, _ = control.apagar(8899)
        self.assertTrue(ok)
        escribir.assert_called_once_with(False)
        untrust.assert_not_called()
        limpiar.assert_not_called()

    def test_apagar_dos_veces_no_rompe(self):
        """Un interruptor de pantalla se aprieta dos veces sin querer."""

        from aegis_agent.install import windows

        with self._con_estado(ruteado=False), \
             patch.object(windows, "write_proxy_settings") as escribir:
            ok, _ = control.apagar(8899)
        self.assertTrue(ok)
        escribir.assert_not_called()

    def test_prender_lo_ya_prendido_no_rompe(self):
        from aegis_agent.install import windows

        with self._con_estado(situacion=control.PROTEGIENDO, ruteado=True, escuchando=True), \
             patch.object(windows, "enrutar") as enrutar:
            ok, _ = control.prender(8899)
        self.assertTrue(ok)
        enrutar.assert_not_called()

    def test_alternar_va_para_el_lado_que_falta(self):
        with self._con_estado(ruteado=True), patch.object(control, "apagar") as apagar:
            control.alternar(8899)
        apagar.assert_called_once()

        with self._con_estado(ruteado=False), patch.object(control, "prender") as prender:
            control.alternar(8899)
        prender.assert_called_once()


if __name__ == "__main__":
    unittest.main()
