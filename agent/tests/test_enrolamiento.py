"""El código que ata un equipo a una empresa, y el agujero que cierra.

`POST /v1/events` no pedía NADA. Cualquiera con la URL podía mandar un evento
con el `tenant_id` que se le ocurriera y quedaba guardado: inventar incidentes
en el panel de una empresa, atribuírselos a una persona real, o llenarlo de
ruido hasta que nadie lo mire. En un producto cuyo valor es el registro, un
registro donde cualquiera escribe no vale nada.

Y del otro lado faltaba la mitad simétrica: el instalador nunca configuraba a
dónde reportar, así que un agente recién instalado protegía el equipo y no le
hablaba a ningún panel. La empresa lo veía vacío y concluía que nadie usa IA.

La regla que sostiene todo esto y que se prueba abajo: **el tenant sale del
token, nunca del cuerpo del evento.** Si el `tenant_id` que manda el agente
decidiera, el token no serviría de nada — bastaría con escribir otro número.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))

from aegis_backend import enrolamiento  # noqa: E402


class TestElCodigoSeEscribeAMano(unittest.TestCase):
    """Alguien lo copia de una pantalla a un instalador. Se diseña para eso."""

    def test_no_lleva_letras_que_se_confunden_con_un_digito(self):
        """I, L, O y U no se generan nunca: se leen como 1, 1, 0 y V."""

        for _ in range(40):
            codigo = enrolamiento.crear("acme")["codigo"]
            cuerpo = codigo.removeprefix("AEGIS-")
            for prohibido in "ILOU":
                with self.subTest(codigo=codigo, caracter=prohibido):
                    self.assertNotIn(prohibido, cuerpo)

    def test_leer_mal_un_caracter_no_deja_a_nadie_afuera(self):
        """La asimetria es el peor error: leo un 0, escribo una O, "no existe".

        Lo encontro un test: la primera version sacaba la S del alfabeto pero
        dejaba el 5, asi que ese error no tenia arreglo del lado de la persona.
        """

        codigo = enrolamiento.crear("acme")["codigo"]
        tecleado = codigo.replace("0", "O").replace("1", "I")
        self.assertIsNotNone(
            enrolamiento.canjear(tecleado), f"{codigo} tecleado como {tecleado}"
        )

    def test_se_acepta_sin_guiones_y_en_minusculas(self):
        """La mitad de la gente omite los guiones y la otra mitad lo pega con espacios."""

        codigo = enrolamiento.crear("acme")["codigo"]
        for variante in (
            codigo,
            codigo.lower(),
            codigo.replace("-", ""),
            f"  {codigo}  ",
            codigo.replace("-", " "),
        ):
            with self.subTest(variante=variante):
                self.assertIsNotNone(enrolamiento.canjear(variante))

    def test_dos_codigos_no_se_repiten(self):
        codigos = {enrolamiento.crear("acme")["codigo"] for _ in range(50)}
        self.assertEqual(len(codigos), 50)


class TestElCanje(unittest.TestCase):
    def test_un_codigo_bueno_da_el_tenant_y_un_token(self):
        codigo = enrolamiento.crear("bancolombia")["codigo"]
        canje = enrolamiento.canjear(codigo)
        self.assertEqual(canje["tenant"], "bancolombia")
        self.assertTrue(canje["token"])

    def test_un_codigo_inventado_no_sirve(self):
        self.assertIsNone(enrolamiento.canjear("AEGIS-ZZZZ-ZZZZ"))

    def test_un_codigo_vencido_no_sirve(self):
        creado = enrolamiento.crear("acme", ahora=1000)
        self.assertIsNone(
            enrolamiento.canjear(
                creado["codigo"], ahora=1000 + enrolamiento.VIGENCIA + 1
            )
        )

    def test_un_codigo_revocado_no_sirve(self):
        codigo = enrolamiento.crear("acme")["codigo"]
        self.assertTrue(enrolamiento.revocar(codigo))
        self.assertIsNone(enrolamiento.canjear(codigo))

    def test_el_codigo_no_es_la_credencial(self):
        """Se puede pasar por chat: leerlo no deja leer los eventos de nadie.

        Por eso se canjea por un token en vez de viajar en cada evento.
        """

        codigo = enrolamiento.crear("acme")["codigo"]
        self.assertIsNone(enrolamiento.leer_equipo(codigo))
        self.assertIsNone(enrolamiento.tenant_del_encabezado(f"Bearer {codigo}"))


def _equipo(tenant: str = "acme", **kwargs) -> str:
    """Un token de equipo como sale en la vida real: canjeando un codigo.

    Existe porque `emitir_equipo` pide el codigo, y lo pide para poder darlo de
    baja despues. Fabricar el token sin fila detras probaria un camino que en
    produccion no ocurre.
    """

    codigo = enrolamiento.crear(tenant)["codigo"]
    return enrolamiento.emitir_equipo(tenant, codigo, **kwargs)


class TestElTokenDeEquipo(unittest.TestCase):
    def test_dice_de_que_empresa_es_el_equipo(self):
        token = _equipo()
        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {token}"), "acme")

    def test_un_token_manoseado_no_vale(self):
        token = _equipo()
        crudo, firma = token.split(".")
        # Se cambia el cuerpo dejando la firma vieja: es el ataque obvio.
        otro = _equipo("bancolombia").split(".")[0]
        self.assertIsNone(enrolamiento.leer_equipo(f"{otro}.{firma}"))

    def test_una_sesion_de_persona_no_sirve_como_equipo(self):
        """Y al reves: dos credenciales distintas para dos cosas distintas."""

        from aegis_backend import cuentas

        sesion = cuentas.emitir("admin", "acme", "admin")
        self.assertIsNone(enrolamiento.leer_equipo(sesion))

    def test_los_dos_formatos_dicen_que_son_adentro_de_la_firma(self):
        """Y no se distinguen por casualidad, que es como estaban antes.

        Los dos tokens comparten llave y formato de cable. Lo unico que impedia
        cruzarlos eran dos chequeos que no se pusieron para eso: a la sesion se
        le pedia `vence` --que el de equipo no lleva-- y al de equipo `tipo`.
        Bastaba con darle expiracion al token de equipo, que es la mitad natural
        de hacerlo revocable, para que pasara a ser una sesion valida. Y sin
        `rol`. Este caso fija que la separacion sea el claim y no el descuido.
        """

        from aegis_backend import cuentas

        self.assertEqual(cuentas.leer(cuentas.emitir("a", "acme", "admin"))["tipo"],
                         cuentas.TIPO)
        self.assertEqual(enrolamiento.leer_equipo(_equipo())["tipo"],
                         enrolamiento.TIPO)
        self.assertNotEqual(cuentas.TIPO, enrolamiento.TIPO)

    def test_un_token_de_equipo_con_expiracion_sigue_sin_abrir_el_panel(self):
        """La trampa concreta: agregarle `vence` al token de equipo.

        Es lo primero que va a hacer quien quiera acortarle la vida, y antes del
        claim de tipo lo convertia en una sesion administradora.
        """

        import time

        from aegis_backend import cuentas

        # Firmado con la llave de verdad: el ataque no es falsificar la firma
        # --no se puede-- sino usar una credencial legitima donde no va.
        falso = cuentas.firmar(
            {
                "tipo": "equipo",
                "tenant": "acme",
                "jti": "AEGISXXXXYYYY",
                "vence": int(time.time()) + 9999,
            }
        )
        self.assertIsNone(cuentas.leer(falso))

    def test_un_token_de_equipo_no_abre_el_panel(self):
        from aegis_backend import cuentas

        equipo = _equipo()
        self.assertIsNone(cuentas.leer(equipo))

    def test_el_token_de_equipo_no_vence(self):
        """Un equipo instalado no tiene a nadie que lo renueve.

        Una sesion de persona vence a las ocho horas porque hay alguien para
        volver a entrar. Un agente que deja de reportar en silencio es justo el
        estado que todo esto existe para evitar; se revoca por codigo, no por
        tiempo.
        """

        token = _equipo(ahora=0)
        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {token}"), "acme")


class TestDarDeBajaUnEquipo(unittest.TestCase):
    """Que el token no venza obliga a que revocarlo funcione de verdad.

    El modulo siempre dijo "se revoca por codigo, no por tiempo". Durante un
    tiempo la primera mitad estaba y la segunda no: `revocar` frenaba canjes
    futuros y el equipo YA enrolado seguia reportando para siempre, porque el
    token no guardaba de que codigo habia salido. Estos casos son esa promesa,
    escrita como test para que no se pueda volver a perder.
    """

    def test_revocar_el_codigo_deja_afuera_al_equipo_ya_enrolado(self):
        codigo = enrolamiento.crear("acme")["codigo"]
        token = enrolamiento.canjear(codigo)["token"]
        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {token}"), "acme")

        self.assertTrue(enrolamiento.revocar(codigo))

        self.assertIsNone(enrolamiento.leer_equipo(token))
        self.assertIsNone(enrolamiento.tenant_del_encabezado(f"Bearer {token}"))

    def test_revocar_un_codigo_no_toca_a_los_equipos_de_otro(self):
        """La baja tiene que ser del codigo revocado y de ninguno mas."""

        vivo = enrolamiento.canjear(enrolamiento.crear("acme")["codigo"])["token"]
        condenado = enrolamiento.crear("acme")["codigo"]
        enrolamiento.canjear(condenado)

        enrolamiento.revocar(condenado)

        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {vivo}"), "acme")

    def test_un_token_sin_jti_no_vale(self):
        """Los de antes de que la revocacion existiera.

        Se rechazan y no se toleran: un token que no se puede atar a ninguna
        fila es exactamente la credencial imposible de dar de baja que este
        cambio vino a sacar. El equipo se vuelve a enrolar, que son diez
        segundos.
        """

        antiguo = _sin_jti("acme")
        self.assertIsNone(enrolamiento.leer_equipo(antiguo))


def _sin_jti(tenant: str) -> str:
    """Un token de equipo del formato viejo, firmado de verdad."""

    from aegis_backend import cuentas

    return cuentas.firmar({"tipo": "equipo", "tenant": tenant, "desde": 0})


class TestElAislamiento(unittest.TestCase):
    def test_los_codigos_de_una_empresa_no_los_ve_otra(self):
        propio = enrolamiento.crear("acme")["codigo"]
        ajeno = enrolamiento.crear("bancolombia")["codigo"]
        mios = {c["codigo"] for c in enrolamiento.listar("acme")}
        self.assertIn(enrolamiento._normalizar(propio), mios)
        self.assertNotIn(enrolamiento._normalizar(ajeno), mios)


if __name__ == "__main__":
    unittest.main()
