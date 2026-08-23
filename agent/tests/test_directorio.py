"""La empresa, su gente, y las herramientas que corren en ella.

Todo esto estaba escrito a mano en el frontend: diez personas en un archivo
`.ts`, un inventario de agentes inventado, y un registro de empresa que no
mandaba nada a ningun lado.

Lo que se prueba, por orden de lo que importa:

  1. **Que el aislamiento por empresa siga valiendo** ahora que hay tres tablas
     mas. Cada tabla nueva es una superficie nueva por donde una empresa podria
     ver a otra, y el tenant tiene que salir del token en todas.
  2. **Que los intentos se crucen sin que el evento sepa quien es la persona.**
     Es la bisagra del diseno: `actor.user_id` es un seudonimo, el nombre vive
     solo en el directorio, y el panel los junta.
  3. **Que la shadow AI se descubra sola.** El inventario no puede depender de
     que alguien escriba a mano las herramientas que justamente nadie declaro.
  4. Que un CSV con una fila mala no cancele las otras cuarenta y nueve.
"""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "web"))

from aegis_backend import cuentas, directorio  # noqa: E402


def _evento(eid: str, tenant: str, usuario: str, proceso: str) -> dict:
    return {
        "event_id": eid,
        "tenant_id": tenant,
        "actor": {"user_id": usuario, "area": "ingenieria", "role": "employee"},
        "destination": {
            "domain": "chatgpt.com",
            "classification": "ai_unapproved",
            "process": proceso,
        },
        "detection": {
            "rule_id": "aws_access_key_id",
            "category": "secret",
            "severity": "critical",
            "confidence": 1.0,
            "engine": "t1_rules",
            "evidence": "AKIA****",
        },
        "action": "blocked",
        "payload_stats": {"bytes": 10, "truncated": False},
        "occurred_at": "2026-08-22T10:00:00Z",
        "agent_version": "0.1.0",
    }


class TestGuardarGente(unittest.TestCase):
    def setUp(self):
        directorio._memoria.clear()
        self.addCleanup(directorio._memoria.clear)

    def test_uno_se_guarda_y_se_lee(self):
        directorio.guardar_colaborador("acme", {"usuario": "miniguez", "nombre": "Marcos"})
        self.assertEqual(len(directorio.colaboradores("acme")), 1)

    def test_el_usuario_no_distingue_mayusculas(self):
        # Es la bisagra con actor.user_id, que el agente manda en minuscula.
        directorio.guardar_colaborador("acme", {"usuario": "MIniguez", "nombre": "Marcos"})
        self.assertEqual(directorio.colaboradores("acme")[0]["usuario"], "miniguez")

    def test_guardar_dos_veces_actualiza_en_vez_de_duplicar(self):
        directorio.guardar_colaborador("acme", {"usuario": "m", "nombre": "Marcos"})
        directorio.guardar_colaborador("acme", {"usuario": "m", "nombre": "Marcos I."})
        gente = directorio.colaboradores("acme")
        self.assertEqual(len(gente), 1)
        self.assertEqual(gente[0]["nombre"], "Marcos I.")

    def test_sin_usuario_o_sin_nombre_no_se_guarda(self):
        # Sin usuario no se cruza con ningun evento; sin nombre no sirve para
        # mostrar. Las dos son filas que solo ocupan lugar.
        self.assertIsNone(directorio.guardar_colaborador("acme", {"nombre": "Marcos"}))
        self.assertIsNone(directorio.guardar_colaborador("acme", {"usuario": "m"}))

    def test_un_estado_inventado_cae_a_pendiente(self):
        fila = directorio.guardar_colaborador(
            "acme", {"usuario": "m", "nombre": "M", "estado": "jubilado"}
        )
        self.assertEqual(fila["estado"], "pendiente")

    def test_una_fila_mala_no_cancela_al_resto_del_csv(self):
        guardadas = directorio.guardar_colaboradores(
            "acme",
            [
                {"usuario": "a", "nombre": "Ana"},
                {"nombre": "sin usuario"},
                {"usuario": "b", "nombre": "Beto"},
            ],
        )
        self.assertEqual(len(guardadas), 2)
        self.assertEqual(len(directorio.colaboradores("acme")), 2)

    def test_borrar(self):
        directorio.guardar_colaborador("acme", {"usuario": "m", "nombre": "M"})
        directorio.borrar_colaborador("acme", "m")
        self.assertEqual(directorio.colaboradores("acme"), [])


class TestUnaEmpresaNoVeLaGenteDeOtra(unittest.TestCase):
    def setUp(self):
        directorio._memoria.clear()
        self.addCleanup(directorio._memoria.clear)

    def test_los_directorios_estan_separados(self):
        directorio.guardar_colaborador("acme", {"usuario": "m", "nombre": "Marcos"})
        directorio.guardar_colaborador("otra", {"usuario": "r", "nombre": "Renata"})
        self.assertEqual([c["nombre"] for c in directorio.colaboradores("acme")], ["Marcos"])
        self.assertEqual([c["nombre"] for c in directorio.colaboradores("otra")], ["Renata"])

    def test_el_mismo_usuario_puede_existir_en_dos_empresas(self):
        # `usuario` es unico dentro de una empresa, no en el mundo: dos empresas
        # pueden tener un "jperez" y no son la misma persona.
        directorio.guardar_colaborador("acme", {"usuario": "jperez", "nombre": "Juan"})
        directorio.guardar_colaborador("otra", {"usuario": "jperez", "nombre": "Julia"})
        self.assertEqual(directorio.colaboradores("acme")[0]["nombre"], "Juan")
        self.assertEqual(directorio.colaboradores("otra")[0]["nombre"], "Julia")

    def test_los_inventarios_estan_separados(self):
        directorio.guardar_en_inventario("acme", {"clase": "agente", "nombre": "cursor"})
        self.assertEqual(directorio.inventario("otra"), [])


class TestLaShadowAiSeDescubreSola(unittest.TestCase):
    """El inventario no puede esperar a que alguien escriba lo que nadie declaro."""

    def setUp(self):
        directorio._memoria.clear()
        self.addCleanup(directorio._memoria.clear)

    def test_una_herramienta_vista_en_un_evento_entra_al_inventario(self):
        directorio.descubrir_desde_eventos(
            "acme", [_evento("1", "acme", "m", "gemini-cli")]
        )
        nombres = [f["nombre"] for f in directorio.inventario("acme")]
        self.assertIn("gemini-cli", nombres)

    def test_entra_como_no_catalogada(self):
        # Es la definicion de shadow AI: se delato usandose, nadie la aprobo.
        directorio.descubrir_desde_eventos("acme", [_evento("1", "acme", "m", "gemini-cli")])
        self.assertEqual(directorio.inventario("acme")[0]["estado"], "no-catalogado")

    def test_arrastra_quien_la_uso(self):
        directorio.descubrir_desde_eventos(
            "acme",
            [
                _evento("1", "acme", "marcos", "gemini-cli"),
                _evento("2", "acme", "renata", "gemini-cli"),
            ],
        )
        self.assertEqual(directorio.inventario("acme")[0]["usuarios"], ["marcos", "renata"])

    def test_no_pisa_lo_que_alguien_ya_aprobo(self):
        # Alguien decidio ese estado a mano; descubrir no puede deshacerlo.
        directorio.guardar_en_inventario(
            "acme", {"clase": "agente", "nombre": "cursor", "estado": "aprobado"}
        )
        directorio.descubrir_desde_eventos("acme", [_evento("1", "acme", "m", "cursor")])
        self.assertEqual(directorio.inventario("acme")[0]["estado"], "aprobado")

    def test_lo_que_no_se_pudo_atribuir_no_inventa_una_herramienta(self):
        for proceso in ("", "desconocido"):
            with self.subTest(proceso=proceso):
                directorio._memoria.clear()
                directorio.descubrir_desde_eventos(
                    "acme", [_evento("1", "acme", "m", proceso)]
                )
                self.assertEqual(directorio.inventario("acme"), [])


class TestPorElApi(unittest.TestCase):
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
        directorio._memoria.clear()
        cuentas._memoria.clear()
        self.addCleanup(directorio._memoria.clear)
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("admin", "admin", "acme")
        cuentas.guardar("otra", "otra", "la-competencia")

        self.servicio._memoria.clear()
        self.servicio._cache = {}
        self.addCleanup(self.servicio._memoria.clear)

    def pedir(self, metodo, ruta, cuerpo=None, token=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            cabeceras = {"Content-Type": "application/json"}
            if token:
                cabeceras["Authorization"] = f"Bearer {token}"
            conexion.request(
                metodo,
                ruta,
                json.dumps(cuerpo).encode() if cuerpo is not None else None,
                cabeceras,
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
        _, datos = self.pedir("POST", "/v1/login", {"usuario": usuario, "password": password})
        return datos["token"]

    def test_las_tres_rutas_nuevas_piden_sesion(self):
        # Cada tabla nueva es una superficie nueva por donde una empresa podria
        # ver a otra.
        for ruta in ("/v1/colaboradores", "/v1/inventario", "/v1/tenant"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("GET", ruta)[0], 401)
                self.assertEqual(self.pedir("POST", ruta, {})[0], 401)

    def test_borrar_tambien_pide_sesion(self):
        self.assertEqual(self.pedir("DELETE", "/v1/colaboradores/m")[0], 401)

    def test_alta_y_lectura(self):
        token = self.entrar("admin", "admin")
        estado, datos = self.pedir(
            "POST", "/v1/colaboradores", {"usuario": "miniguez", "nombre": "Marcos"}, token
        )
        self.assertEqual(estado, 200)
        self.assertEqual(datos["descartados"], 0)

        _, leidos = self.pedir("GET", "/v1/colaboradores", token=token)
        self.assertEqual(leidos["colaboradores"][0]["nombre"], "Marcos")

    def test_el_csv_reporta_cuantas_filas_descarto(self):
        token = self.entrar("admin", "admin")
        _, datos = self.pedir(
            "POST",
            "/v1/colaboradores",
            {"colaboradores": [{"usuario": "a", "nombre": "Ana"}, {"nombre": "rota"}]},
            token,
        )
        self.assertEqual(len(datos["guardados"]), 1)
        self.assertEqual(datos["descartados"], 1)

    def test_una_empresa_no_ve_el_directorio_de_otra(self):
        self.pedir(
            "POST", "/v1/colaboradores", {"usuario": "m", "nombre": "Marcos"},
            self.entrar("admin", "admin"),
        )
        _, otra = self.pedir("GET", "/v1/colaboradores", token=self.entrar("otra", "otra"))
        self.assertEqual(otra["colaboradores"], [])

    def test_los_intentos_se_cruzan_por_el_seudonimo(self):
        """La bisagra del diseno.

        El evento nunca lleva el nombre de la persona: lleva `user_id`, que es
        un seudonimo. El nombre vive solo en el directorio. El panel puede decir
        "Marcos reincide" cruzando las dos tablas, y el agente sigue sin saber
        quien es Marcos.
        """

        token = self.entrar("admin", "admin")
        self.pedir("POST", "/v1/colaboradores", {"usuario": "miniguez", "nombre": "Marcos"}, token)
        self.servicio._memoria.insert(0, _evento("1", "acme", "miniguez", "browser"))
        self.servicio._memoria.insert(0, _evento("2", "acme", "miniguez", "browser"))

        _, datos = self.pedir("GET", "/v1/colaboradores", token=token)
        self.assertEqual(datos["colaboradores"][0]["intentos"], 2)

    def test_el_tenant_del_cuerpo_no_puede_renombrar_otra_empresa(self):
        token = self.entrar("admin", "admin")
        self.pedir("POST", "/v1/tenant", {"tenant": "la-competencia", "nombre": "Robada"}, token)

        _, otra = self.pedir("GET", "/v1/tenant", token=self.entrar("otra", "otra"))
        self.assertNotEqual(otra.get("nombre"), "Robada")

    def test_el_inventario_descubre_al_listar(self):
        token = self.entrar("admin", "admin")
        self.servicio._memoria.insert(0, _evento("1", "acme", "m", "gemini-cli"))
        _, datos = self.pedir("GET", "/v1/inventario", token=token)
        self.assertIn("gemini-cli", [f["nombre"] for f in datos["inventario"]])


if __name__ == "__main__":
    unittest.main()
