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


class TestElTokenDeEquipo(unittest.TestCase):
    def test_dice_de_que_empresa_es_el_equipo(self):
        token = enrolamiento.emitir_equipo("acme")
        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {token}"), "acme")

    def test_un_token_manoseado_no_vale(self):
        token = enrolamiento.emitir_equipo("acme")
        crudo, firma = token.split(".")
        # Se cambia el cuerpo dejando la firma vieja: es el ataque obvio.
        otro = enrolamiento.emitir_equipo("bancolombia").split(".")[0]
        self.assertIsNone(enrolamiento.leer_equipo(f"{otro}.{firma}"))

    def test_una_sesion_de_persona_no_sirve_como_equipo(self):
        """Y al reves: dos credenciales distintas para dos cosas distintas."""

        from aegis_backend import cuentas

        sesion = cuentas.emitir("admin", "acme", "admin")
        self.assertIsNone(enrolamiento.leer_equipo(sesion))

    def test_un_token_de_equipo_no_abre_el_panel(self):
        from aegis_backend import cuentas

        equipo = enrolamiento.emitir_equipo("acme")
        self.assertIsNone(cuentas.leer(equipo))

    def test_el_token_de_equipo_no_vence(self):
        """Un equipo instalado no tiene a nadie que lo renueve.

        Una sesion de persona vence a las ocho horas porque hay alguien para
        volver a entrar. Un agente que deja de reportar en silencio es justo el
        estado que todo esto existe para evitar; se revoca por codigo, no por
        tiempo.
        """

        token = enrolamiento.emitir_equipo("acme", ahora=0)
        self.assertEqual(enrolamiento.tenant_del_encabezado(f"Bearer {token}"), "acme")


class TestElAislamiento(unittest.TestCase):
    def test_los_codigos_de_una_empresa_no_los_ve_otra(self):
        propio = enrolamiento.crear("acme")["codigo"]
        ajeno = enrolamiento.crear("bancolombia")["codigo"]
        mios = {c["codigo"] for c in enrolamiento.listar("acme")}
        self.assertIn(enrolamiento._normalizar(propio), mios)
        self.assertNotIn(enrolamiento._normalizar(ajeno), mios)


if __name__ == "__main__":
    unittest.main()
