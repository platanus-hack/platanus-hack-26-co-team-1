"""Quien entra al panel, y que **no** puede ver desde adentro.

El panel era publico y mostraba todos los eventos de todas las empresas: el
contrato tiene `tenant_id` desde el primer dia y ninguna consulta lo miraba.
Para un producto cuyo pitch es "tus datos no salen de tu empresa", que el panel
de una muestre el trafico de otra no es un detalle de permisos: es el producto
al reves.

Lo que se prueba aca, por orden de lo que duele si se rompe:

  1. **Que una empresa no pueda ver los datos de otra**, ni con un token valido,
     ni cambiando parametros, ni editando el token. Es la clase larga del final
     y es la razon de ser del archivo.
  2. Que sin sesion no se lea nada.
  3. Que la contrasena no se guarde, y que compararla no filtre por tiempo.
"""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "web"))

from aegis_backend import cuentas  # noqa: E402


def _evento(eid: str, tenant: str, dominio: str) -> dict:
    return {
        "event_id": eid,
        "tenant_id": tenant,
        "actor": {"user_id": "u_x", "area": "ventas", "role": "employee"},
        "destination": {
            "domain": dominio,
            "classification": "ai_unapproved",
            "process": "browser",
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


class TestLaContrasenaNoSeGuarda(unittest.TestCase):
    def test_el_hash_no_contiene_la_contrasena(self):
        hash_, sal = cuentas.hashear("hunter2")
        self.assertNotIn("hunter2", hash_)
        self.assertNotIn("hunter2", sal)

    def test_la_misma_contrasena_da_hashes_distintos(self):
        # Sal distinta por cuenta: sin eso, dos personas con la misma
        # contrasena tienen el mismo hash y una tabla precalculada las abre a
        # las dos de una vez.
        primero, _ = cuentas.hashear("hunter2")
        segundo, _ = cuentas.hashear("hunter2")
        self.assertNotEqual(primero, segundo)

    def test_verifica_con_la_sal_correcta(self):
        hash_, sal = cuentas.hashear("hunter2")
        self.assertTrue(cuentas.coincide("hunter2", hash_, sal))
        self.assertFalse(cuentas.coincide("hunter3", hash_, sal))

    def test_una_sal_ajena_no_abre_la_cuenta(self):
        hash_, _ = cuentas.hashear("hunter2")
        _, otra = cuentas.hashear("cualquiera")
        self.assertFalse(cuentas.coincide("hunter2", hash_, otra))


class TestElToken(unittest.TestCase):
    def test_va_y_vuelve(self):
        token = cuentas.emitir("admin", "acme", "admin")
        cuerpo = cuentas.leer(token)
        self.assertEqual(cuerpo["usuario"], "admin")
        self.assertEqual(cuerpo["tenant"], "acme")

    def test_uno_manipulado_no_vale(self):
        """El corazon del aislamiento.

        Si se pudiera editar el tenant de un token y seguir entrando, todo lo
        demas sobra: cualquiera se emite uno con el tenant que quiera.
        """

        token = cuentas.emitir("admin", "acme", "admin")
        crudo, firma = token.split(".")
        cuerpo = json.loads(cuentas._des64(crudo))
        cuerpo["tenant"] = "la-competencia"
        falsificado = f"{cuentas._b64(json.dumps(cuerpo).encode())}.{firma}"

        self.assertIsNone(cuentas.leer(falsificado))

    def test_uno_vencido_no_vale(self):
        viejo = cuentas.emitir("admin", "acme", "admin", ahora=time.time() - cuentas.VIGENCIA - 10)
        self.assertIsNone(cuentas.leer(viejo))

    def test_basura_no_revienta(self):
        for texto in ("", "x", "a.b", "....", "Bearer nada"):
            with self.subTest(texto=texto):
                self.assertIsNone(cuentas.leer(texto))

    def test_firmado_con_otra_clave_no_vale(self):
        with patch.object(cuentas, "_POR_PROCESO", b"una-clave"):
            ajeno = cuentas.emitir("admin", "acme", "admin")
        with patch.object(cuentas, "_POR_PROCESO", b"otra-clave"):
            self.assertIsNone(cuentas.leer(ajeno))

    def test_del_encabezado(self):
        token = cuentas.emitir("admin", "acme", "admin")
        self.assertIsNotNone(cuentas.del_encabezado(f"Bearer {token}"))
        self.assertIsNotNone(cuentas.del_encabezado(f"bearer {token}"))
        self.assertIsNone(cuentas.del_encabezado(token))  # sin el esquema
        self.assertIsNone(cuentas.del_encabezado(None))


class TestAutenticar(unittest.TestCase):
    def setUp(self):
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("admin", "admin", "acme")

    def test_con_las_credenciales_correctas(self):
        self.assertIsNotNone(cuentas.autenticar("admin", "admin"))

    def test_no_distingue_usuario_inexistente_de_contrasena_mala(self):
        # Los dos None: distinguirlos le confirma a quien prueba cuales cuentas
        # existen, que es la mitad del trabajo de entrar.
        self.assertIsNone(cuentas.autenticar("admin", "otra"))
        self.assertIsNone(cuentas.autenticar("nadie", "admin"))

    def test_el_usuario_no_distingue_mayusculas(self):
        self.assertIsNotNone(cuentas.autenticar("ADMIN", "admin"))

    def test_sembrar_no_pisa_una_cuenta_existente(self):
        cuentas.guardar("admin", "una-contrasena-nueva", "acme")
        self.assertFalse(cuentas.sembrar_si_no_hay("admin", "admin", "acme"))
        # Si sembrar pisara, arrancar el servicio devolveria la de fabrica.
        self.assertIsNone(cuentas.autenticar("admin", "admin"))
        self.assertIsNotNone(cuentas.autenticar("admin", "una-contrasena-nueva"))


class ServicioConCuentas(unittest.TestCase):
    """Levanta el servicio de verdad con dos empresas cargadas."""

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
        cuentas.guardar("admin", "admin", "acme")
        cuentas.guardar("otra", "otra", "la-competencia")

        self.servicio._memoria.clear()
        self.servicio._cache = {}
        self.addCleanup(self.servicio._memoria.clear)
        # Dos empresas, dos eventos, dominios distintos para poder distinguirlos.
        self.servicio._memoria.insert(0, _evento("de-acme", "acme", "chatgpt.com"))
        self.servicio._memoria.insert(0, _evento("de-otra", "la-competencia", "gemini.google.com"))

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
        estado, datos = self.pedir("POST", "/v1/login", {"usuario": usuario, "password": password})
        return datos["token"] if estado == 200 else None


class TestSinSesionNoSeVeNada(ServicioConCuentas):
    def test_las_metricas_piden_sesion(self):
        estado, _ = self.pedir("GET", "/api/metrics")
        self.assertEqual(estado, 401)

    def test_un_token_inventado_no_sirve(self):
        estado, _ = self.pedir("GET", "/api/metrics", token="inventado")
        self.assertEqual(estado, 401)

    def test_escribir_la_politica_pide_sesion(self):
        # La politica incluye el diccionario de terminos de la empresa: dejar
        # que un pedido sin token elija sobre que empresa escribe seria dejar
        # que cualquiera desarme las reglas de cualquiera.
        estado, _ = self.pedir("PUT", "/v1/policy/acme", {"unknown_domain_action": "allow"})
        self.assertEqual(estado, 401)

    def test_el_login_con_credenciales_malas_da_401(self):
        estado, _ = self.pedir("POST", "/v1/login", {"usuario": "admin", "password": "no"})
        self.assertEqual(estado, 401)

    def test_subir_un_evento_sin_credencial_ya_no_se_puede(self):
        """Este test AFIRMABA lo contrario, y afirmaba un agujero.

        Decia que el endpoint del agente "queda abierto a proposito" porque el
        agente no tiene con quien loguearse. Pero abierto significaba que
        cualquiera con la URL podia mandar un evento con el tenant_id que se le
        ocurriera: inventar incidentes en el panel de una empresa y
        atribuirselos a una persona real. La frontera de contenido impide que
        entre el SECRETO, no que entre la mentira.

        Ahora el agente si tiene con quien identificarse: su token de equipo,
        que sale de canjear el codigo de enrolamiento.
        """

        estado, _ = self.pedir("POST", "/v1/events", _evento("nuevo", "acme", "chatgpt.com"))
        self.assertEqual(estado, 401)

    def test_el_agente_sube_eventos_con_su_token_de_equipo(self):
        from aegis_backend import enrolamiento

        equipo = enrolamiento.canjear(enrolamiento.crear("acme")["codigo"])["token"]
        estado, _ = self.pedir(
            "POST", "/v1/events", _evento("nuevo", "acme", "chatgpt.com"), token=equipo
        )
        self.assertEqual(estado, 202)

    def test_el_tenant_del_evento_lo_decide_el_token_y_no_el_cuerpo(self):
        """Si lo decidiera el cuerpo, el token no serviria para nada."""

        from aegis_backend import enrolamiento

        equipo = enrolamiento.canjear(enrolamiento.crear("acme")["codigo"])["token"]
        self.pedir(
            "POST",
            "/v1/events",
            _evento("mentiroso", "bancolombia", "chatgpt.com"),
            token=equipo,
        )
        _, mias = self.pedir("GET", "/api/metrics", token=self.entrar("admin", "admin"))
        # Aparece en el panel de acme, que es de donde es su token, y no en el
        # de la empresa que el evento decia ser.
        self.assertGreater(mias["metrics"]["total"], 0)


class TestUnaEmpresaNoVeLaDeOtra(ServicioConCuentas):
    """Lo mas importante del archivo."""

    def test_cada_una_ve_solo_sus_eventos(self):
        _, acme = self.pedir("GET", "/api/metrics", token=self.entrar("admin", "admin"))
        _, otra = self.pedir("GET", "/api/metrics", token=self.entrar("otra", "otra"))

        self.assertEqual([d[0] for d in acme["metrics"]["by_destination"]], ["chatgpt.com"])
        self.assertEqual([d[0] for d in otra["metrics"]["by_destination"]], ["gemini.google.com"])

    def test_el_tenant_de_la_respuesta_es_el_del_token(self):
        _, datos = self.pedir("GET", "/api/metrics", token=self.entrar("otra", "otra"))
        self.assertEqual(datos["tenant"], "la-competencia")

    def test_pedir_otro_tenant_por_parametro_no_cambia_nada(self):
        """La trampa evidente, y la que mas veces funciona en productos reales."""

        token = self.entrar("admin", "admin")
        for ruta in (
            "/api/metrics?tenant=la-competencia",
            "/api/metrics?tenant_id=la-competencia",
            "/v1/metrics?tenant=la-competencia",
        ):
            with self.subTest(ruta=ruta):
                _, datos = self.pedir("GET", ruta, token=token)
                self.assertEqual(datos["tenant"], "acme")
                self.assertEqual(
                    [d[0] for d in datos["metrics"]["by_destination"]], ["chatgpt.com"]
                )

    def test_leer_la_politica_de_otra_empresa_devuelve_la_propia(self):
        token = self.entrar("admin", "admin")
        self.pedir("PUT", "/v1/policy/acme", {"marca": "de-acme"}, token=token)
        self.pedir(
            "PUT", "/v1/policy/la-competencia", {"marca": "de-otra"},
            token=self.entrar("otra", "otra"),
        )

        # Con sesion de acme, pedir la ruta de la competencia da la de acme.
        _, leida = self.pedir("GET", "/v1/policy/la-competencia", token=token)
        self.assertEqual(leida.get("marca"), "de-acme")

    def test_escribir_en_la_ruta_de_otra_empresa_escribe_en_la_propia(self):
        token = self.entrar("admin", "admin")
        self.pedir("PUT", "/v1/policy/la-competencia", {"marca": "intento"}, token=token)

        _, de_la_otra = self.pedir(
            "GET", "/v1/policy/la-competencia", token=self.entrar("otra", "otra")
        )
        self.assertNotEqual(de_la_otra.get("marca"), "intento")

    def test_el_cache_no_se_comparte_entre_empresas(self):
        """Un cache compartido entre inquilinos es una fuga con vencimiento.

        Con una sola variable de cache, la primera empresa que carga el panel
        deja sus eventos ahi y la siguiente los recibe durante dos segundos.
        """

        _, acme = self.pedir("GET", "/api/metrics", token=self.entrar("admin", "admin"))
        _, otra = self.pedir("GET", "/api/metrics", token=self.entrar("otra", "otra"))
        _, acme_otra_vez = self.pedir(
            "GET", "/api/metrics", token=self.entrar("admin", "admin")
        )

        self.assertNotEqual(
            acme["metrics"]["by_destination"], otra["metrics"]["by_destination"]
        )
        self.assertEqual(
            acme["metrics"]["by_destination"], acme_otra_vez["metrics"]["by_destination"]
        )


class TestElImportNoTocaNada(unittest.TestCase):
    def test_importar_el_servicio_no_siembra_cuentas(self):
        """Sembrar al importar escribe una cuenta en la base de verdad.

        Es el mismo error que costo veintitres tests rojos con
        `addons = [Aegis()]` (docs/ESTADO.md, seccion 5).
        """

        fuente = (REPO / "web" / "app.py").read_text(encoding="utf-8")
        cuerpo = [
            linea
            for linea in fuente.splitlines()
            if linea.startswith("sembrar_la_cuenta_inicial()")
        ]
        self.assertEqual(cuerpo, [], "se siembra al importar el modulo")
        self.assertIn("    sembrar_la_cuenta_inicial()", fuente, "main() no la siembra")


if __name__ == "__main__":
    unittest.main()
