"""Quien puede entrar al panel de una empresa, y quien lo decide.

## Por que existe este archivo

Hasta aca habia UNA cuenta por empresa: la que crea el registro. El rol se
emitia en el token, se guardaba en la tabla y se devolvia al frontend, pero no
existia forma de crear una segunda cuenta, asi que `LECTOR` era inalcanzable y
la unica cuenta posible era administradora. Un rol que no se puede asignar no es
un permiso, es un campo.

## Lo que hay que mirar con cuidado

Agregar esta pantalla abre una puerta que antes no existia: **el usuario es la
clave de la tabla y `guardar` hace upsert**. Un admin que escribe el nombre de
un usuario de otra empresa le pisaria la contrasena y el tenant, o sea se
queda con su cuenta. Es la unica forma de cruzar la frontera entre empresas que
quedaba, y aparece justo con esta funcion. La clase `TestLaFronteraEntreEmpresas`
es la que la cierra, y es la mas importante del archivo.

Lo segundo es el candado: una empresa que se queda sin ningun admin no puede
deshacer nada --ni siquiera lo que la dejo asi-- y la unica salida es entrar a
la base a mano.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "web"))

from tests.panel import PanelLevantado  # noqa: E402
from aegis_backend import cuentas  # noqa: E402

CLAVE = "clave-larga-1"
OTRA = "clave-larga-2"


class Base(PanelLevantado):
    def setUp(self):
        super().setUp()
        cuentas._memoria.clear()
        self.addCleanup(cuentas._memoria.clear)
        cuentas.guardar("jefa", CLAVE, "acme", rol=cuentas.ADMIN)
        cuentas.guardar("mirona", OTRA, "acme", rol=cuentas.LECTOR)
        cuentas.guardar("ajena", OTRA, "la-competencia", rol=cuentas.ADMIN)
        self.admin = self.entrar("jefa", CLAVE)
        self.lector = self.entrar("mirona", OTRA)


class TestVerElEquipo(Base):
    def test_se_ve_quien_entra_y_con_que_permiso(self):
        estado, datos = self.pedir("GET", "/v1/usuarios", token=self.admin)
        self.assertEqual(estado, 200)
        self.assertEqual(
            datos["usuarios"],
            [{"usuario": "jefa", "rol": "admin"}, {"usuario": "mirona", "rol": "lector"}],
        )

    def test_un_lector_puede_ver_la_lista(self):
        """Tiene que poder saber a quien pedirle lo que el no puede hacer."""

        estado, datos = self.pedir("GET", "/v1/usuarios", token=self.lector)
        self.assertEqual(estado, 200)
        self.assertEqual(len(datos["usuarios"]), 2)

    def test_sin_sesion_no_se_ve_nada(self):
        self.assertEqual(self.pedir("GET", "/v1/usuarios")[0], 401)

    def test_la_lista_no_lleva_hashes(self):
        """El hash de scrypt es caro de romper, no imposible.

        Y una lista de hashes en un JSON es una lista de hashes en el historial
        del navegador, en los logs de un proxy y en cualquier extension que lea
        la pagina.
        """

        _, datos = self.pedir("GET", "/v1/usuarios", token=self.admin)
        crudo = str(datos)
        self.assertNotIn("hash", crudo)
        self.assertNotIn("sal", crudo)


class TestSumarYSacar(Base):
    def test_un_admin_suma_a_alguien_y_ese_alguien_entra(self):
        estado, datos = self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "nuevo", "password": "clave-larga-3", "rol": "lector"},
            token=self.admin,
        )
        self.assertEqual(estado, 200)
        self.assertEqual(datos, {"usuario": "nuevo", "rol": "lector"})
        self.assertIsNotNone(self.entrar("nuevo", "clave-larga-3"))

    def test_quien_se_suma_como_lector_no_puede_escribir(self):
        """El circuito entero: el rol se asigna y despues se hace valer."""

        self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "nuevo", "password": "clave-larga-3", "rol": "lector"},
            token=self.admin,
        )
        suyo = self.entrar("nuevo", "clave-larga-3")
        self.assertEqual(self.pedir("POST", "/v1/tenant", {}, token=suyo)[0], 403)

    def test_un_lector_no_suma_a_nadie(self):
        estado, _ = self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "colado", "password": "clave-larga-3", "rol": "admin"},
            token=self.lector,
        )
        self.assertEqual(estado, 403)

    def test_una_contrasena_corta_no_pasa(self):
        estado, _ = self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "nuevo", "password": "corta", "rol": "lector"},
            token=self.admin,
        )
        self.assertEqual(estado, 409)

    def test_un_rol_inventado_no_pasa(self):
        estado, _ = self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "nuevo", "password": "clave-larga-3", "rol": "dios"},
            token=self.admin,
        )
        self.assertEqual(estado, 409)

    def test_cambiar_el_rol_de_alguien(self):
        estado, datos = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "mirona", "rol": "admin"}, token=self.admin
        )
        self.assertEqual(estado, 200)
        self.assertEqual(datos["rol"], "admin")
        # Y el permiso nuevo vale de verdad, no solo en la tabla.
        suyo = self.entrar("mirona", OTRA)
        self.assertEqual(self.pedir("POST", "/v1/tenant", {}, token=suyo)[0], 200)

    def test_dar_de_baja(self):
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "mirona", "baja": True}, token=self.admin
        )
        self.assertEqual(estado, 200)
        self.assertIsNone(self.entrar("mirona", OTRA))


class TestElCandado(Base):
    """Una empresa no se puede quedar sin nadie que la administre.

    Si pasa, no hay forma de deshacerlo desde el producto --ni siquiera de
    deshacer lo que la dejo asi-- y la unica salida es que alguien entre a la
    base a mano.
    """

    def test_el_ultimo_admin_no_se_puede_dar_de_baja(self):
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "jefa", "baja": True}, token=self.admin
        )
        self.assertEqual(estado, 409)
        self.assertIsNotNone(self.entrar("jefa", CLAVE))

    def test_el_ultimo_admin_no_se_puede_degradar(self):
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "jefa", "rol": "lector"}, token=self.admin
        )
        self.assertEqual(estado, 409)

    def test_con_dos_admins_si_se_puede_salir(self):
        """El candado es contra quedarse sin ninguno, no contra irse."""

        self.pedir(
            "POST", "/v1/usuarios", {"usuario": "mirona", "rol": "admin"}, token=self.admin
        )
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "jefa", "rol": "lector"}, token=self.admin
        )
        self.assertEqual(estado, 200)


class TestLaFronteraEntreEmpresas(Base):
    """La clase que importa.

    El usuario es la clave de la tabla y `guardar` hace upsert, asi que sin
    estos chequeos el admin de una empresa se queda con la cuenta de otra
    escribiendo su nombre. Es la unica forma de cruzar la frontera que quedaba
    abierta, y la abre justo esta funcion.
    """

    def test_no_se_puede_robar_el_usuario_de_otra_empresa(self):
        estado, _ = self.pedir(
            "POST",
            "/v1/usuarios",
            {"usuario": "ajena", "password": "me-la-quedo-yo", "rol": "admin"},
            token=self.admin,
        )
        self.assertEqual(estado, 409)
        # Y la duena sigue entrando con la suya, en su empresa.
        suyo = self.entrar("ajena", OTRA)
        self.assertIsNotNone(suyo)
        self.assertEqual(cuentas.leer(suyo)["tenant"], "la-competencia")

    def test_no_se_puede_cambiar_el_rol_de_otra_empresa(self):
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "ajena", "rol": "lector"}, token=self.admin
        )
        self.assertEqual(estado, 409)
        self.assertEqual(cuentas.rol_de(cuentas.buscar("ajena")), "admin")

    def test_no_se_puede_dar_de_baja_a_otra_empresa(self):
        estado, _ = self.pedir(
            "POST", "/v1/usuarios", {"usuario": "ajena", "baja": True}, token=self.admin
        )
        self.assertEqual(estado, 409)
        self.assertIsNotNone(self.entrar("ajena", OTRA))

    def test_el_equipo_de_una_empresa_no_lo_ve_otra(self):
        _, datos = self.pedir("GET", "/v1/usuarios", token=self.admin)
        self.assertNotIn("ajena", [u["usuario"] for u in datos["usuarios"]])

    def test_el_candado_cuenta_admins_de_SU_empresa(self):
        """Y no de todas.

        Si contara global, el admin de acme no podria degradarse porque existe
        un admin en la-competencia -- o peor, al reves: podria vaciarse de
        admins porque los cuenta de otra.
        """

        self.assertFalse(cuentas._quedan_admins("acme", sin="jefa"))
        self.assertTrue(cuentas._quedan_admins("la-competencia", sin="jefa"))
