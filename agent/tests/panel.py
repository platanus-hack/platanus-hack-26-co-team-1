"""El panel levantado de verdad, para los tests que lo prueban por HTTP.

Estaba copiado en `test_cuentas_y_aislamiento.py` y en `test_directorio.py`:
las mismas treinta y tres lineas para levantar el servidor en un puerto libre,
mandar un pedido con token y parsear la respuesta. Dos copias de un arnes no son
un problema de estilo -- son dos lugares donde arreglar un timeout, y uno de los
dos se olvida.

Va aca y no en `aislamiento.py` porque son cosas distintas: aquel impide que la
suite toque produccion, este levanta un panel de mentira. Quien use este casi
siempre quiere tambien aquel.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import unittest
from http.server import ThreadingHTTPServer


class PanelLevantado(unittest.TestCase):
    """Base para los tests que le hablan al panel por la red.

    El servidor se levanta una vez por clase --arrancarlo por caso multiplica
    los sockets sin probar nada nuevo-- y el puerto se pide al sistema en vez de
    fijarlo, para que dos suites en paralelo no se peleen.

    Las subclases que definan `setUp` tienen que llamar a `super().setUp()`: es
    lo que deja el contador de intentos limpio.
    """

    @classmethod
    def setUpClass(cls):
        import app as servicio

        cls.servicio = servicio
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.puerto = s.getsockname()[1]
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", cls.puerto), servicio.Handler)
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        # El limite de intentos es estado de proceso y vive entre tests: sin
        # esto, una clase que prueba contrasenas malas deja sin turno a la que
        # corre despues, y el fallo aparece o no segun el orden.
        from aegis_backend import intentos

        intentos.reiniciar()
        self.addCleanup(intentos.reiniciar)

    def pedir(self, metodo, ruta, cuerpo=None, token=None, cabeceras=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            enviadas = {"Content-Type": "application/json", **(cabeceras or {})}
            if token:
                enviadas["Authorization"] = f"Bearer {token}"
            conexion.request(
                metodo,
                ruta,
                json.dumps(cuerpo).encode() if cuerpo is not None else None,
                enviadas,
            )
            respuesta = conexion.getresponse()
            crudo = respuesta.read()
            try:
                datos = json.loads(crudo)
            except ValueError:
                datos = None
            return respuesta.status, datos
        finally:
            conexion.close()

    def entrar(self, usuario, password):
        """El token de una sesion, o None si las credenciales no sirven."""

        estado, datos = self.pedir(
            "POST", "/v1/login", {"usuario": usuario, "password": password}
        )
        return datos["token"] if estado == 200 and datos else None
