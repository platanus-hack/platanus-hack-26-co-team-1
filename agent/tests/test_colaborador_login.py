"""El colaborador tambien tiene que poder entrar, no solo el admin.

Hasta aca "Colaboradores" era un directorio -nombre, area, cargo- separado por
completo de las cuentas con contrasena: se podia dar de alta a alguien en el
panel y esa persona seguia sin tener con que loguearse en ningun lado, y
`/colaborador/login` mandaba a cualquiera que entrara directo a `/admin/panel`
sin mirar el rol.

Lo que se prueba aca, por orden de lo que duele si se rompe:

  1. Que dar de alta a un colaborador le cree una cuenta de verdad, con una
     temporal que se ve UNA sola vez.
  2. Que esa persona pueda cambiar su propia contrasena, y solo la propia.
  3. Que "mi actividad" le muestre sus intentos y los de nadie mas -ni de un
     companero, ni de otra empresa-.
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

from aegis_backend import cuentas  # noqa: E402


def _evento(eid: str, tenant: str, usuario: str, dominio: str = "chatgpt.com") -> dict:
    return {
        "event_id": eid,
        "tenant_id": tenant,
        "actor": {"user_id": usuario, "area": "ventas", "role": "employee"},
        "destination": {"domain": dominio, "classification": "ai_unapproved", "process": "browser"},
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


class TestLaTemporal(unittest.TestCase):
    def test_no_repite_caracteres_ambiguos(self):
        # 0/O/1/l/I afuera: alguien la tiene que poder leer en voz alta.
        temporal = cuentas.generar_password_temporal()
        for caracter in "0O1lI":
            self.assertNotIn(caracter, temporal)

    def test_dos_llamadas_no_dan_lo_mismo(self):
        self.assertNotEqual(cuentas.generar_password_temporal(), cuentas.generar_password_temporal())


class TestCambiarPassword(unittest.TestCase):
    def setUp(self):
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("ana", "temporal-123", "acme", rol="colaborador", debe_cambiar=True)

    def test_con_la_actual_correcta_cambia(self):
        self.assertTrue(cuentas.cambiar_password("ana", "temporal-123", "una-nueva-mejor"))
        self.assertIsNotNone(cuentas.autenticar("ana", "una-nueva-mejor"))
        self.assertIsNone(cuentas.autenticar("ana", "temporal-123"))

    def test_con_la_actual_mala_no_cambia_nada(self):
        self.assertFalse(cuentas.cambiar_password("ana", "otra-cosa", "una-nueva-mejor"))
        self.assertIsNotNone(cuentas.autenticar("ana", "temporal-123"))

    def test_cambiar_apaga_debe_cambiar(self):
        cuentas.cambiar_password("ana", "temporal-123", "una-nueva-mejor")
        cuenta = cuentas.buscar("ana")
        self.assertFalse(cuenta.get("debe_cambiar"))

    def test_una_cuenta_que_no_existe_no_cambia(self):
        self.assertFalse(cuentas.cambiar_password("nadie", "loquesea", "una-nueva-mejor"))


class ServicioConColaboradores(unittest.TestCase):
    """Levanta el servicio de verdad, sin ninguna cuenta precargada."""

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
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("admin", "admin-pw", "acme")

        self.servicio._memoria.clear()
        self.servicio._cache = {}
        self.addCleanup(self.servicio._memoria.clear)

        import aegis_backend.directorio as directorio

        directorio._memoria.clear()
        self.addCleanup(directorio._memoria.clear)

    def pedir(self, metodo, ruta, cuerpo=None, token=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            cabeceras = {"Content-Type": "application/json"}
            if token:
                cabeceras["Authorization"] = f"Bearer {token}"
            conexion.request(
                metodo, ruta, json.dumps(cuerpo).encode() if cuerpo is not None else None, cabeceras
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
        estado, datos = self.pedir("POST", "/v1/login", {"usuario": usuario, "password": password})
        return datos if estado == 200 else None


class TestAltaCreaCuenta(ServicioConColaboradores):
    def test_dar_de_alta_devuelve_una_temporal(self):
        token = self.entrar("admin", "admin-pw")["token"]
        estado, datos = self.pedir(
            "POST",
            "/v1/colaboradores",
            {"colaboradores": [{"usuario": "ana", "nombre": "Ana Gómez", "area": "ventas"}]},
            token=token,
        )
        self.assertEqual(estado, 200)
        self.assertIn("password_temporal", datos["guardados"][0])

    def test_la_temporal_de_verdad_sirve_para_entrar(self):
        token = self.entrar("admin", "admin-pw")["token"]
        _, datos = self.pedir(
            "POST", "/v1/colaboradores", {"colaboradores": [{"usuario": "ana", "nombre": "Ana"}]}, token=token
        )
        temporal = datos["guardados"][0]["password_temporal"]

        sesion = self.entrar("ana", temporal)
        self.assertIsNotNone(sesion)
        self.assertEqual(sesion["rol"], "colaborador")
        self.assertTrue(sesion["debe_cambiar_password"])

    def test_re_subir_el_mismo_usuario_no_resetea_la_contrasena(self):
        # Corregir el area de alguien en un segundo CSV no puede devolverle la
        # cuenta a una temporal que ya cambio.
        token = self.entrar("admin", "admin-pw")["token"]
        _, primera = self.pedir(
            "POST", "/v1/colaboradores", {"colaboradores": [{"usuario": "ana", "nombre": "Ana"}]}, token=token
        )
        temporal = primera["guardados"][0]["password_temporal"]
        cuentas.cambiar_password("ana", temporal, "la-que-eligio-ana")

        _, segunda = self.pedir(
            "POST",
            "/v1/colaboradores",
            {"colaboradores": [{"usuario": "ana", "nombre": "Ana", "area": "legal"}]},
            token=token,
        )
        self.assertNotIn("password_temporal", segunda["guardados"][0])
        self.assertIsNotNone(cuentas.autenticar("ana", "la-que-eligio-ana"))

    def test_el_admin_no_recibe_temporal_de_su_propia_cuenta(self):
        # El admin ya tenia cuenta antes del alta: no hay nada que provisionar.
        token = self.entrar("admin", "admin-pw")["token"]
        _, datos = self.pedir(
            "POST",
            "/v1/colaboradores",
            {"colaboradores": [{"usuario": "admin", "nombre": "El admin, otra vez"}]},
            token=token,
        )
        self.assertNotIn("password_temporal", datos["guardados"][0])


class TestCambiarPasswordPorHttp(ServicioConColaboradores):
    def setUp(self):
        super().setUp()
        cuentas.guardar("ana", "temporal-123", "acme", rol="colaborador", debe_cambiar=True)

    def test_sin_sesion_no_se_puede_cambiar(self):
        estado, _ = self.pedir("PUT", "/v1/password", {"actual": "temporal-123", "nueva": "nueva12345"})
        self.assertEqual(estado, 401)

    def test_con_la_actual_correcta_cambia_y_se_puede_entrar_con_la_nueva(self):
        token = self.entrar("ana", "temporal-123")["token"]
        estado, _ = self.pedir("PUT", "/v1/password", {"actual": "temporal-123", "nueva": "nueva12345"}, token=token)
        self.assertEqual(estado, 200)

        sesion = self.entrar("ana", "nueva12345")
        self.assertIsNotNone(sesion)
        self.assertFalse(sesion["debe_cambiar_password"])

    def test_con_la_actual_mala_no_cambia(self):
        token = self.entrar("ana", "temporal-123")["token"]
        estado, _ = self.pedir("PUT", "/v1/password", {"actual": "cualquier-otra", "nueva": "nueva12345"}, token=token)
        self.assertEqual(estado, 401)
        self.assertIsNotNone(cuentas.autenticar("ana", "temporal-123"))

    def test_una_nueva_muy_corta_se_rechaza(self):
        token = self.entrar("ana", "temporal-123")["token"]
        estado, _ = self.pedir("PUT", "/v1/password", {"actual": "temporal-123", "nueva": "corta"}, token=token)
        self.assertEqual(estado, 400)

    def test_no_se_puede_cambiar_la_contrasena_de_otra_cuenta(self):
        # El endpoint no toma "usuario" del cuerpo: sale de la sesion, siempre.
        cuentas.guardar("bruno", "otra-temporal", "acme", rol="colaborador")
        token = self.entrar("ana", "temporal-123")["token"]
        self.pedir("PUT", "/v1/password", {"actual": "otra-temporal", "nueva": "nueva12345"}, token=token)
        self.assertIsNotNone(cuentas.autenticar("bruno", "otra-temporal"))


class TestBorrarQuitaLasDosCosas(ServicioConColaboradores):
    def test_borrar_un_colaborador_le_saca_tambien_el_login(self):
        token = self.entrar("admin", "admin-pw")["token"]
        self.pedir(
            "POST", "/v1/colaboradores", {"colaboradores": [{"usuario": "ana", "nombre": "Ana"}]}, token=token
        )
        self.assertIsNotNone(cuentas.buscar("ana"))

        estado, _ = self.pedir("DELETE", "/v1/colaboradores/ana", token=token)
        self.assertEqual(estado, 200)
        self.assertIsNone(cuentas.buscar("ana"))

    def test_no_se_lleva_puesta_una_cuenta_de_admin_con_el_mismo_usuario(self):
        # Defensivo: si "admin" apareciera en /v1/colaboradores/admin por
        # cualquier motivo, la ruta no puede borrar la cuenta de administracion.
        token = self.entrar("admin", "admin-pw")["token"]
        estado, _ = self.pedir("DELETE", "/v1/colaboradores/admin", token=token)
        self.assertEqual(estado, 200)
        self.assertIsNotNone(cuentas.buscar("admin"))


class TestUnColaboradorNoEntraAlPanelDeAdmin(ServicioConColaboradores):
    """El otro lado de la moneda: mi-actividad y password son de cualquiera,
    todo lo demas es solo del admin -y antes de esto, no lo era."""

    def setUp(self):
        super().setUp()
        cuentas.guardar("ana", "temporal-ana", "acme", rol="colaborador")

    def test_metricas_le_dan_403_y_no_401(self):
        # 403 y no 401 porque SI tiene sesion: el problema es el rol, no que
        # le falte loguearse. Confundir los dos manda a cualquiera a reintentar
        # un login que ya funciono.
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("GET", "/api/metrics", token=token)
        self.assertEqual(estado, 403)

    def test_insights_tambien(self):
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("GET", "/api/insights", token=token)
        self.assertEqual(estado, 403)

    def test_listar_colaboradores_tambien(self):
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("GET", "/v1/colaboradores", token=token)
        self.assertEqual(estado, 403)

    def test_no_puede_dar_de_alta_a_otro_colaborador(self):
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir(
            "POST", "/v1/colaboradores", {"colaboradores": [{"usuario": "x", "nombre": "X"}]}, token=token
        )
        self.assertEqual(estado, 403)

    def test_no_puede_reescribir_la_politica(self):
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("PUT", "/v1/policy/acme", {"unknown_domain_action": "allow"}, token=token)
        self.assertEqual(estado, 403)

    def test_no_puede_borrar_a_otro_colaborador(self):
        cuentas.guardar("bruno", "pw", "acme", rol="colaborador")
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("DELETE", "/v1/colaboradores/bruno", token=token)
        self.assertEqual(estado, 403)

    def test_pero_si_puede_ver_y_cambiar_lo_suyo(self):
        # El contrapeso: el rol no le apago el acceso a TODO, solo a lo ajeno.
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, _ = self.pedir("GET", "/v1/mi-actividad", token=token)
        self.assertEqual(estado, 200)
        estado, _ = self.pedir("PUT", "/v1/password", {"actual": "temporal-ana", "nueva": "nueva12345"}, token=token)
        self.assertEqual(estado, 200)


class TestMiActividad(ServicioConColaboradores):
    def setUp(self):
        super().setUp()
        cuentas.guardar("ana", "temporal-ana", "acme", rol="colaborador")
        cuentas.guardar("bruno", "temporal-bruno", "acme", rol="colaborador")
        cuentas.guardar("otra-empresa-admin", "pw", "la-competencia")

        self.servicio._memoria.insert(0, _evento("e-ana", "acme", "ana", "chatgpt.com"))
        self.servicio._memoria.insert(0, _evento("e-bruno", "acme", "bruno", "gemini.google.com"))
        self.servicio._memoria.insert(0, _evento("e-otra-empresa", "la-competencia", "ana", "claude.ai"))

    def test_sin_sesion_no_se_ve_nada(self):
        estado, _ = self.pedir("GET", "/v1/mi-actividad")
        self.assertEqual(estado, 401)

    def test_ana_solo_ve_lo_suyo(self):
        token = self.entrar("ana", "temporal-ana")["token"]
        estado, datos = self.pedir("GET", "/v1/mi-actividad", token=token)
        self.assertEqual(estado, 200)
        dominios = [e["domain"] for e in datos["actividad"]]
        self.assertEqual(dominios, ["chatgpt.com"])

    def test_no_se_cuela_el_intento_de_un_companero(self):
        token = self.entrar("bruno", "temporal-bruno")["token"]
        _, datos = self.pedir("GET", "/v1/mi-actividad", token=token)
        dominios = [e["domain"] for e in datos["actividad"]]
        self.assertEqual(dominios, ["gemini.google.com"])

    def test_el_mismo_seudonimo_en_otra_empresa_no_se_cuela(self):
        # "ana" existe en dos tenants y tiene un evento en cada uno: el de la
        # competencia no puede aparecer aunque el seudonimo coincida.
        token = self.entrar("ana", "temporal-ana")["token"]
        _, datos = self.pedir("GET", "/v1/mi-actividad", token=token)
        self.assertEqual(len(datos["actividad"]), 1)
        self.assertEqual(datos["actividad"][0]["domain"], "chatgpt.com")

    def test_no_devuelve_contenido_ni_evidencia_cruda(self):
        # No hace falta: el evento ya viene redactado del agente (ADR 0003),
        # pero esto confirma que la ruta no agrega nada de mas por su cuenta.
        token = self.entrar("ana", "temporal-ana")["token"]
        _, datos = self.pedir("GET", "/v1/mi-actividad", token=token)
        entrada = datos["actividad"][0]
        self.assertEqual(
            set(entrada.keys()),
            {"occurred_at", "process", "domain", "classification", "action", "rule_id", "category", "severity"},
        )


if __name__ == "__main__":
    unittest.main()
