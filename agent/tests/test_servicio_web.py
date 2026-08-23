"""El servicio desplegado: el front y el API por la misma URL.

Aegis se despliega como un solo web service que sirve dos cosas: el API que el
panel consume y el panel en si, que es la app Angular de `frontend/`. Van juntos
a proposito. Separados hacen falta dos servicios, una URL para cada uno y CORS
en el medio, todo para que dos piezas del mismo producto se hablen.

Lo que se cubre aca, por orden de lo que duele si se rompe:

  1. **Que no se pueda leer cualquier archivo de la maquina.** Servir archivos
     de disco desde un proceso publico es la forma mas facil de convertir un
     panel en una fuga. Es la trampa clasica y hay que probarla con pedidos
     crudos, porque los clientes normales normalizan la ruta antes de mandarla y
     el ataque nunca llega.
  2. Que el enrutado del lado del cliente funcione: `/admin/politicas` no existe
     como archivo, y sin devolver el index, compartir un enlace da 404.
  3. Que el API siga estando donde estaba.
  4. Que sin build del front el servicio no se caiga: queda el panel en HTML.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "web"))

import app as servicio  # noqa: E402


def _puerto_libre() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServicioVivo(unittest.TestCase):
    """Levanta el servicio de verdad: lo que se prueba es el enrutado real."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.puerto = _puerto_libre()
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", cls.puerto), servicio.Handler)
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def pedir(self, ruta: str, crudo: bool = False):
        """Pide una ruta. Con `crudo`, sin dejar que el cliente la normalice."""

        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            if crudo:
                conexion.putrequest("GET", ruta, skip_accept_encoding=True)
                conexion.endheaders()
            else:
                conexion.request("GET", ruta)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.read()
        finally:
            conexion.close()


class TestNoSePuedeLeerLaMaquina(ServicioVivo):
    """Lo mas importante: este proceso es publico y sirve archivos de disco."""

    # Cada una escapa de otra forma. Las que llevan %2f y %2e existen porque un
    # cliente normal normaliza la ruta y el ataque nunca sale del navegador: hay
    # que mandarlas crudas para que lleguen tal cual.
    ESCAPES = (
        "/../../web/app.py",
        "/..%2f..%2fweb%2fapp.py",
        "/%2e%2e/%2e%2e/web/app.py",
        "/../../../../etc/passwd",
        "/....//....//web/app.py",
    )

    def test_ninguna_ruta_que_sale_de_dist_devuelve_un_archivo_de_la_maquina(self):
        for ruta in self.ESCAPES:
            with self.subTest(ruta=ruta):
                _, cuerpo = self.pedir(ruta, crudo=True)
                # Se busca contenido del propio codigo fuente: si aparece, la
                # ruta salio de dist y sirvio un archivo del repositorio.
                self.assertNotIn(b"scan_payload", cuerpo)
                self.assertNotIn(b"def main", cuerpo)
                self.assertNotIn(b"ANTHROPIC_API_KEY", cuerpo)
                self.assertNotIn(b"root:x:", cuerpo)

    def test_una_ruta_que_escapa_cae_en_el_index_o_en_un_404(self):
        # No alcanza con que no filtre: tiene que responder algo razonable.
        for ruta in self.ESCAPES:
            with self.subTest(ruta=ruta):
                estado, _ = self.pedir(ruta, crudo=True)
                self.assertIn(estado, (200, 404))


class TestElApiSigueDondeEstaba(ServicioVivo):
    def test_health(self):
        estado, cuerpo = self.pedir("/v1/health")
        self.assertEqual(estado, 200)
        self.assertTrue(json.loads(cuerpo)["ok"])

    def test_las_metricas_no_se_sirven_sin_sesion(self):
        # Cambio de contrato: /api/metrics era publico y mostraba los eventos de
        # TODAS las empresas. Ver tests/test_cuentas_y_aislamiento.py.
        estado, _ = self.pedir("/api/metrics")
        self.assertEqual(estado, 401)

    def test_metricas_con_sesion(self):
        sys.path.insert(0, str(REPO / "backend"))
        from aegis_backend import cuentas

        token = cuentas.emitir("admin", "acme", "admin")
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            conexion.request("GET", "/api/metrics", headers={"Authorization": f"Bearer {token}"})
            respuesta = conexion.getresponse()
            estado, cuerpo = respuesta.status, respuesta.read()
        finally:
            conexion.close()

        self.assertEqual(estado, 200)
        datos = json.loads(cuerpo)
        self.assertIn("metrics", datos)
        # block_rate es una propiedad y no un campo: si alguien cambia como se
        # serializa, el panel se queda sin el numero mas visible.
        self.assertIn("block_rate", datos["metrics"])

    def test_las_metricas_aceptan_un_rango_de_fechas(self):
        # La semana simulada (`demo_data.py`) cae toda entre el 18 y el 22 de
        # agosto de 2026: un `desde` posterior a eso tiene que dejar el panel
        # en cero, sin que el fallback a la maqueta lo tape.
        sys.path.insert(0, str(REPO / "backend"))
        from aegis_backend import cuentas

        token = cuentas.emitir("admin", "acme", "admin")
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        try:
            conexion.request(
                "GET",
                "/api/metrics?desde=2030-01-01T00:00:00Z",
                headers={"Authorization": f"Bearer {token}"},
            )
            respuesta = conexion.getresponse()
            estado, cuerpo = respuesta.status, respuesta.read()
        finally:
            conexion.close()

        self.assertEqual(estado, 200)
        datos = json.loads(cuerpo)
        self.assertEqual(datos["metrics"]["total"], 0)
        self.assertEqual(datos["eventos"], 0)

    def test_los_insights_no_se_sirven_sin_sesion(self):
        estado, _ = self.pedir("/api/insights")
        self.assertEqual(estado, 401)

    def test_los_insights_con_sesion(self):
        # `MODELO_INSIGHTS` se pisa a `None` a proposito: el test no puede
        # depender de si quien lo corre tiene `ANTHROPIC_API_KEY` puesta, ni
        # pagar una llamada real cada vez que corre la suite.
        sys.path.insert(0, str(REPO / "backend"))
        from aegis_backend import cuentas

        token = cuentas.emitir("admin", "acme", "admin")
        with patch.object(servicio, "MODELO_INSIGHTS", None):
            conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
            try:
                conexion.request("GET", "/api/insights", headers={"Authorization": f"Bearer {token}"})
                respuesta = conexion.getresponse()
                estado, cuerpo = respuesta.status, respuesta.read()
            finally:
                conexion.close()

        self.assertEqual(estado, 200)
        datos = json.loads(cuerpo)
        self.assertEqual(datos["generado_por"], "estatico")
        self.assertTrue(datos["resumen"])
        self.assertTrue(datos["insights"])
        self.assertTrue(datos["estrategias"])

    def test_los_insights_respetan_el_mismo_rango_que_las_metricas(self):
        sys.path.insert(0, str(REPO / "backend"))
        from aegis_backend import cuentas, insights as insights_mod

        token = cuentas.emitir("admin", "acme", "admin")
        with patch.object(servicio, "MODELO_INSIGHTS", None):
            conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
            try:
                conexion.request(
                    "GET",
                    "/api/insights?desde=2030-01-01T00:00:00Z",
                    headers={"Authorization": f"Bearer {token}"},
                )
                respuesta = conexion.getresponse()
                estado, cuerpo = respuesta.status, respuesta.read()
            finally:
                conexion.close()

        self.assertEqual(estado, 200)
        datos = json.loads(cuerpo)
        # Un rango en el futuro no tiene eventos: tiene que caer en el
        # respaldo de "semana en cero" y no fingir un riesgo inventado.
        self.assertEqual(
            {k: v for k, v in datos.items() if k != "generado_por"},
            insights_mod.RESPALDO_SIN_DATOS,
        )

    def test_el_panel_en_html_sigue_accesible(self):
        # Es el respaldo cuando no hay build, y sirve para ver las metricas
        # crudas sin depender de que el front compile.
        estado, cuerpo = self.pedir("/panel")
        self.assertEqual(estado, 200)
        self.assertIn(b"Aegis", cuerpo)


@unittest.skipUnless(servicio.hay_front(), "el front no esta construido")
class TestElFrontSeSirve(ServicioVivo):
    def test_la_portada_es_la_app(self):
        estado, cuerpo = self.pedir("/")
        self.assertEqual(estado, 200)
        self.assertIn(b"app-root", cuerpo)

    def test_una_ruta_del_cliente_devuelve_el_index(self):
        # /admin/politicas no existe como archivo. Sin esto, compartir el enlace
        # o recargar la pagina da 404, que es el bug que nadie ve navegando.
        for ruta in ("/admin/politicas", "/admin/panel", "/colaborador/onboarding"):
            with self.subTest(ruta=ruta):
                estado, cuerpo = self.pedir(ruta)
                self.assertEqual(estado, 200)
                self.assertIn(b"app-root", cuerpo)

    def test_los_assets_se_sirven_con_su_tipo(self):
        estado, cuerpo = self.pedir("/favicon.ico")
        self.assertEqual(estado, 200)
        self.assertTrue(cuerpo)


class TestSinFrontElServicioSigueDePie(unittest.TestCase):
    """Un checkout sin npm, o un build que fallo, no pueden dejarlo sin panel."""

    def test_la_portada_cae_al_panel_en_html(self):
        with patch.object(servicio, "DIST", Path("no-existe")):
            self.assertFalse(servicio.hay_front())

            puerto = _puerto_libre()
            servidor = ThreadingHTTPServer(("127.0.0.1", puerto), servicio.Handler)
            hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
            hilo.start()
            self.addCleanup(servidor.server_close)
            self.addCleanup(servidor.shutdown)

            conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
            self.addCleanup(conexion.close)
            conexion.request("GET", "/")
            respuesta = conexion.getresponse()
            cuerpo = respuesta.read()

            self.assertEqual(respuesta.status, 200)
            self.assertIn(b"Aegis", cuerpo)


if __name__ == "__main__":
    unittest.main()


class TestLaBaseColaborativaSincroniza(ServicioVivo):
    """`/v1/domains/sync` tiene que ganarle al prefijo `/v1/domains/`.

    Es la ruta de la que vive la promesa de que el catalogo crece solo: un
    dominio que investigo UN equipo lo terminan conociendo todos porque cada
    agente baja este delta cada cinco minutos.

    Estuvo rota en produccion y nadie lo noto, porque falla de la peor manera
    posible: "sync" caia en el manejador generico como si fuera el nombre de un
    dominio y el agente recibia `{"domain": "sync", "classification": "pending"}`.
    Eso no tiene la clave "dominios", asi que `DomainClient.sincronizar()` --que
    esta escrito para aguantar quedarse sin red-- mezclaba una lista vacia, no
    lanzaba nada y no dejaba rastro. El catalogo dejo de crecer en silencio.

    El backend hermano (`aegis_backend/app.py`) ya tenia un comentario avisando
    de exactamente esta trampa. No alcanzo. Por eso ahora es un test.
    """

    def test_sync_devuelve_el_delta_y_no_un_veredicto_sobre_el_dominio_sync(self):
        estado, cuerpo = self.pedir("/v1/domains/sync?desde=1970-01-01T00:00:00Z")
        datos = json.loads(cuerpo)
        self.assertEqual(estado, 200)
        self.assertIn("dominios", datos)
        self.assertIn("hasta", datos)
        # La firma exacta de la regresion.
        self.assertNotEqual(datos.get("domain"), "sync")

    def test_sin_desde_tambien_responde_el_delta(self):
        # Es lo que pide un agente en su primer arranque, y lo que promete el
        # docstring de sincronizacion(). Reventaba: la marca vacia llegaba a
        # time.strptime y este endpoint es publico.
        for ruta in ("/v1/domains/sync", "/v1/domains/sync?desde="):
            with self.subTest(ruta=ruta):
                estado, cuerpo = self.pedir(ruta)
                self.assertEqual(estado, 200)
                self.assertIn("dominios", json.loads(cuerpo))

    def test_un_dominio_de_verdad_sigue_yendo_al_manejador_generico(self):
        # El arreglo no puede haberse comido la ruta que ya funcionaba.
        estado, cuerpo = self.pedir("/v1/domains/ejemplo-que-nadie-cataloga.xyz")
        # 202 la primera vez (queda encolado para investigarlo) y 200 si ya
        # habia veredicto. Cual de los dos depende de si otro test toco antes
        # este dominio, y eso no es lo que se esta probando: lo que importa es
        # que el nombre llego entero al manejador generico y no se lo comio la
        # rama de sync.
        self.assertIn(estado, (200, 202))
        self.assertEqual(json.loads(cuerpo).get("domain"), "ejemplo-que-nadie-cataloga.xyz")
