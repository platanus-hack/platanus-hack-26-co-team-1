"""Que pide cada puerta del panel, y que pasa cuando alguien la fuerza.

Los tres agujeros que cubre este archivo salieron de una auditoria y comparten
la misma forma: codigo que se escribio rapido para cerrar el circuito de altas,
donde cada decision estaba bien argumentada en su docstring y ninguna estaba
comprobada por un test.

  1. **Leer la politica no pedia nada.** Y la politica lleva `company_terms`, el
     diccionario de nombres de proyecto y sistemas internos que la empresa carga
     a mano. Con el nombre del tenant --que publica el registro-- cualquiera se
     bajaba la lista de lo que la empresa considera secreto, de un producto que
     existe para que esa lista no salga.
  2. **Los tres endpoints sin sesion aceptaban intentos ilimitados.** Login era
     el que dolia: adivinar contrasenas a la velocidad de la red.
  3. **El rol se emitia y no se comparaba nunca.** Cualquier sesion valida podia
     emitir codigos de enrolamiento.
"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "web"))

from tests.panel import PanelLevantado  # noqa: E402
from aegis_backend import cuentas, enrolamiento, intentos  # noqa: E402

TERMINOS = {"Proyecto Quimera": "codename", "orion-db-prod": "sistema interno"}


class TestLaPoliticaNoEsPublica(PanelLevantado):
    """La politica se le da a quien puede pedirla, y con SU tenant.

    El argumento viejo para no pedir nada era que "la politica es la
    configuracion que el agente OBEDECE, no datos de nadie". Se quedo viejo dos
    veces: lleva el diccionario de la empresa, y el agente ya tiene credencial
    propia desde que existe el enrolamiento.
    """

    def setUp(self):
        super().setUp()
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("admin", "clave-larga-1", "acme")
        cuentas.guardar("ajeno", "clave-larga-2", "la-competencia")
        self.servicio.POLITICAS.put("acme", {"company_terms": dict(TERMINOS)})
        self.addCleanup(self.servicio.POLITICAS.put, "acme", {})

    def test_sin_credencial_no_se_lee(self):
        estado, _ = self.pedir("GET", "/v1/policy/acme")
        self.assertEqual(estado, 401)

    def test_el_panel_de_la_empresa_si_la_lee(self):
        token = self.entrar("admin", "clave-larga-1")
        estado, datos = self.pedir("GET", "/v1/policy/acme", token=token)
        self.assertEqual(estado, 200)
        self.assertEqual(datos["company_terms"], TERMINOS)

    def test_el_agente_enrolado_tambien(self):
        """Es el otro lector legitimo, y por el que esto no puede pedir sesion."""

        codigo = enrolamiento.crear("acme")["codigo"]
        equipo = enrolamiento.canjear(codigo)["token"]
        estado, datos = self.pedir("GET", "/v1/policy/acme", token=equipo)
        self.assertEqual(estado, 200)
        self.assertEqual(datos["company_terms"], TERMINOS)

    def test_otra_empresa_no_se_lleva_el_diccionario(self):
        """Aunque escriba "acme" en la ruta: el tenant sale del token.

        Es el mismo caso que ya gobierna a los eventos y a las metricas. Si la
        ruta decidiera, el token no serviria para nada.
        """

        ajeno = self.entrar("ajeno", "clave-larga-2")
        estado, datos = self.pedir("GET", "/v1/policy/acme", token=ajeno)
        self.assertEqual(estado, 200)
        self.assertEqual(datos.get("company_terms", {}), {})

    def test_un_equipo_de_otra_empresa_tampoco(self):
        codigo = enrolamiento.crear("la-competencia")["codigo"]
        equipo = enrolamiento.canjear(codigo)["token"]
        _, datos = self.pedir("GET", "/v1/policy/acme", token=equipo)
        self.assertEqual(datos.get("company_terms", {}), {})


class TestProbarSaleCaro(PanelLevantado):
    """Nadie prueba credenciales sin limite."""

    def setUp(self):
        super().setUp()
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("admin", "clave-larga-1", "acme")

    def _fallar(self, veces, usuario="admin"):
        ultimos = []
        for _ in range(veces):
            estado, _ = self.pedir(
                "POST", "/v1/login", {"usuario": usuario, "password": "no"}
            )
            ultimos.append(estado)
        return ultimos

    def test_despues_de_varios_fallos_el_login_deja_de_contestar(self):
        estados = self._fallar(intentos.LIBRES + 1)
        self.assertEqual(estados[:intentos.LIBRES], [401] * intentos.LIBRES)
        self.assertEqual(estados[-1], 429)

    def test_agotado_el_turno_ni_la_contrasena_buena_entra(self):
        """Si no, el limite no limita: se prueba igual y se entra al acertar."""

        self._fallar(intentos.LIBRES)
        estado, _ = self.pedir(
            "POST", "/v1/login", {"usuario": "admin", "password": "clave-larga-1"}
        )
        self.assertEqual(estado, 429)

    def test_entrar_bien_limpia_la_cuenta(self):
        """Quien se equivoca cuatro veces y acierta no arrastra el castigo."""

        self._fallar(intentos.LIBRES - 1)
        self.assertIsNotNone(self.entrar("admin", "clave-larga-1"))
        self.assertEqual(self._fallar(1), [401])

    def test_el_429_no_dice_cuantos_intentos_quedan(self):
        """Decirlo le mide el limite a quien esta probando."""

        self._fallar(intentos.LIBRES)
        _, datos = self.pedir("POST", "/v1/login", {"usuario": "admin", "password": "x"})
        self.assertNotIn(str(intentos.LIBRES), str(datos))

    def test_enrolar_tambien_tiene_limite(self):
        estados = []
        for _ in range(intentos.LIBRES + 1):
            estado, _ = self.pedir("POST", "/v1/enrolar", {"codigo": "AEGIS-ZZZZ-ZZZZ"})
            estados.append(estado)
        self.assertEqual(estados[-1], 429)

    def test_registrar_empresas_en_masa_tampoco(self):
        """Aca se cuentan los ACIERTOS: el abuso es ocupar nombres, no fallar."""

        estados = []
        for i in range(intentos.LIBRES + 1):
            estado, _ = self.pedir(
                "POST",
                "/v1/registro",
                {"empresa": f"masiva-{i}", "usuario": f"u{i}", "password": "clave-larga"},
            )
            estados.append(estado)
        self.assertEqual(estados[-1], 429)


class TestElContador(unittest.TestCase):
    """El modulo suelto, sin red de por medio."""

    def setUp(self):
        intentos.reiniciar()
        self.addCleanup(intentos.reiniciar)

    def test_deja_pasar_hasta_el_limite(self):
        for _ in range(intentos.LIBRES):
            self.assertTrue(intentos.permitido("x"))
            intentos.anotar("x")
        self.assertFalse(intentos.permitido("x"))

    def test_una_clave_agotada_frena_aunque_la_otra_tenga_turno(self):
        """Es lo que hace que rotar IPs no alcance."""

        for _ in range(intentos.LIBRES):
            intentos.anotar("usuario:victima")
        self.assertTrue(intentos.permitido("ip:nueva"))
        self.assertFalse(intentos.permitido("ip:nueva", "usuario:victima"))

    def test_pasada_la_ventana_se_vuelve_a_poder(self):
        ahora = 1000.0
        for _ in range(intentos.LIBRES):
            intentos.anotar("x", ahora=ahora)
        self.assertFalse(intentos.permitido("x", ahora=ahora))
        self.assertTrue(intentos.permitido("x", ahora=ahora + intentos.VENTANA + 1))

    def test_olvidar_borra_la_cuenta(self):
        for _ in range(intentos.LIBRES):
            intentos.anotar("x")
        intentos.olvidar("x")
        self.assertTrue(intentos.permitido("x"))

    def test_la_ip_sale_del_x_forwarded_for_cuando_esta(self):
        """Detras de Render todos los pedidos llegan de la misma IP interna.

        Sin esta cabecera habria un solo balde para todo el mundo, y el primero
        que se equivoque deja afuera al resto.
        """

        self.assertEqual(intentos.desde_donde("10.0.0.1", "203.0.113.9, 10.0.0.1"), "203.0.113.9")
        self.assertEqual(intentos.desde_donde("10.0.0.1", None), "10.0.0.1")
        self.assertEqual(intentos.desde_donde("10.0.0.1", "  "), "10.0.0.1")

    def test_el_tiempo_por_defecto_es_el_de_verdad(self):
        """Sin esto los limites solo funcionarian en los tests."""

        intentos.anotar("x")
        self.assertTrue(intentos.permitido("x", ahora=time.time()))


class TestMirarNoEsCambiar(PanelLevantado):
    """El rol dejo de ser decorativo.

    Se emitia, se guardaba, se devolvia al frontend, y no se comparaba en ningun
    lado: cualquier sesion valida podia llamar cualquier escritura, incluida la
    que emite codigos de enrolamiento. No era explotable --todas las cuentas se
    crean admin-- pero un campo de autorizacion que existe invita a confiar en
    el.
    """

    def setUp(self):
        super().setUp()
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("jefa", "clave-larga-1", "acme", rol=cuentas.ADMIN)
        cuentas.guardar("mirona", "clave-larga-2", "acme", rol=cuentas.LECTOR)

    def test_un_admin_escribe(self):
        token = self.entrar("jefa", "clave-larga-1")
        estado, _ = self.pedir("POST", "/v1/enrolamiento", {}, token=token)
        self.assertEqual(estado, 200)

    def test_un_lector_no(self):
        token = self.entrar("mirona", "clave-larga-2")
        for ruta in ("/v1/enrolamiento", "/v1/colaboradores", "/v1/inventario", "/v1/tenant"):
            with self.subTest(ruta=ruta):
                estado, _ = self.pedir("POST", ruta, {}, token=token)
                self.assertEqual(estado, 403)

    def test_un_lector_si_puede_mirar(self):
        """El 403 es de escritura. Quitarle la lectura seria otra cosa."""

        token = self.entrar("mirona", "clave-larga-2")
        self.assertEqual(self.pedir("GET", "/v1/colaboradores", token=token)[0], 200)

    def test_una_cuenta_sin_rol_no_hereda_admin(self):
        """El default cerrado.

        Antes era `cuenta.get("rol", "admin")`: una fila a la que le faltara el
        campo --una migracion a medias, una escritura directa a la tabla-- salia
        administradora. El sentido de un default es cubrir el caso que no se
        penso, y ese caso no deberia poder escribir.
        """

        cuentas._memoria["huerfana"] = {
            "usuario": "huerfana",
            "tenant": "acme",
            **dict(zip(("hash", "sal"), cuentas.hashear("clave-larga-3"))),
        }
        token = self.entrar("huerfana", "clave-larga-3")
        self.assertEqual(self.pedir("POST", "/v1/tenant", {}, token=token)[0], 403)


class TestSonTresRolesYNoDos(PanelLevantado):
    """Mirar el panel de la empresa y ser admin no son lo mismo.

    Salio de juntar dos ramas que inventaron un rol cada una sin verse:

      - `lector` nacio para MIRAR y no tocar, y la puerta que lo hacia posible
        era que las lecturas solo pedian sesion.
      - `colaborador` nacio despues, del otro lado, y cerro TODA lectura de
        empresa detras de "es admin". Correcto para un colaborador -- sus
        eventos son suyos y los de la empresa no son asunto suyo -- y encima
        de `lector`, que se quedo sin su unica funcion.

    Las dos decisiones estaban bien argumentadas y ninguna estaba mal escrita.
    El merge las junto sin conflicto de texto, porque tocaban lineas distintas,
    y el resultado era un rol que solo podia recibir 403. Por eso este archivo
    prueba los tres roles contra la misma puerta: es la unica forma de que la
    proxima rama que invente un cuarto rol se entere de que hay otros tres.
    """

    def setUp(self):
        super().setUp()
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("jefa", "clave-larga-1", "acme", rol=cuentas.ADMIN)
        cuentas.guardar("mirona", "clave-larga-2", "acme", rol=cuentas.LECTOR)
        cuentas.guardar("curioso", "clave-larga-3", "acme", rol="colaborador")

    # Las lecturas de empresa: admin y lector si, colaborador no.

    LECTURAS = ("/v1/colaboradores", "/v1/inventario", "/v1/tenant", "/api/metrics")

    def test_el_admin_lee_el_panel(self):
        token = self.entrar("jefa", "clave-larga-1")
        for ruta in self.LECTURAS:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("GET", ruta, token=token)[0], 200)

    def test_el_lector_lee_el_panel(self):
        """Es su unica funcion. Si esto da 403, el rol no existe."""

        token = self.entrar("mirona", "clave-larga-2")
        for ruta in self.LECTURAS:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("GET", ruta, token=token)[0], 200)

    def test_el_colaborador_no_lee_el_panel(self):
        """403 y no 401: la sesion es buena, lo que no alcanza es el rol.

        La diferencia no es cosmetica. A quien entro bien y recibe "sesion
        requerida" no le queda ninguna pista de que su cuenta es valida y la
        pantalla no es suya.
        """

        token = self.entrar("curioso", "clave-larga-3")
        for ruta in self.LECTURAS:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("GET", ruta, token=token)[0], 403)

    def test_el_colaborador_no_ve_los_codigos_de_enrolamiento(self):
        """La lista de codigos vivos es la lista de formas de sumar un equipo.

        Esta puerta solo pedia sesion, y estaba bien mientras las unicas cuentas
        eran de la empresa mirando a la empresa. Las cuentas de colaborador la
        dejaron abierta sin que ningun test se pusiera rojo.
        """

        token = self.entrar("curioso", "clave-larga-3")
        self.assertEqual(self.pedir("GET", "/v1/enrolamiento", token=token)[0], 403)

    def test_el_lector_si_ve_los_codigos(self):
        token = self.entrar("mirona", "clave-larga-2")
        self.assertEqual(self.pedir("GET", "/v1/enrolamiento", token=token)[0], 200)

    def test_el_colaborador_si_ve_lo_suyo(self):
        """Lo que le queda, y es a proposito: sus propios intentos."""

        token = self.entrar("curioso", "clave-larga-3")
        self.assertEqual(self.pedir("GET", "/v1/mi-actividad", token=token)[0], 200)

    def test_el_colaborador_tampoco_escribe(self):
        token = self.entrar("curioso", "clave-larga-3")
        for ruta in ("/v1/enrolamiento", "/v1/colaboradores", "/v1/tenant"):
            with self.subTest(ruta=ruta):
                self.assertEqual(self.pedir("POST", ruta, {}, token=token)[0], 403)
