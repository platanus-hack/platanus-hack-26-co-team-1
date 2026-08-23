"""Contrasenas contadas en una frase, que es como salen de verdad.

Nadie le escribe `password=...` a un chat. Escribe "entra con la clave
Temporal#2026", y eso no tiene formato: no hay prefijo tipo `sk-` ni largo fijo
ni alfabeto propio. Es la fuga mas grave que existe (una contrasena abre todo lo
que protege) y la que peor cubren las dos mitades del motor:

  - El modelo local encuentra CERO. No es un defecto suyo: un extractor de
    entidades reconoce tipos de cosa, y una contrasena no es un tipo de cosa,
    es una cadena cualquiera que resulta ser secreta por el contexto.
  - Las reglas de formato tampoco, porque justamente no hay formato.

Las cubren dos reglas deterministas que miran la palabra ancla y la FORMA del
valor. Esa forma es la mezcla de clases de caracteres que exige cualquier
politica de contrasenas, no la entropia: `Sup3rS3cret` da 2.91 bits, por debajo
del umbral de `looks_random`, y es exactamente el tipo de clave que una empresa
obliga a poner.

La mitad larga de este archivo son los NEGATIVOS, y es a proposito. Estas reglas
son de categoria `secret`, o sea que BLOQUEAN. Un falso positivo aca no cuesta
ruido en el panel: le corta el trabajo a alguien, y encima al perfil que mas
escribe la palabra "password" en su vida, que es el que programa.
"""

import json
import unittest

from aegis_agent.detect.engine import scan
from aegis_agent.detect.payload import scan_payload
from aegis_agent.detect.entropy import (
    looks_random,
    parece_contrasena,
    parece_expresion_de_codigo,
)
from bench.corpus import CREDENCIALES, NORMAL, TRAMPAS_DE_CREDENCIAL


def _secretos(texto: str) -> list[str]:
    return [f.rule_id for f in scan(texto) if f.category == "secret"]


class TestLasCredencialesDelCorpusNoSeEscapan(unittest.TestCase):
    """Ninguna de las ocho puede salir. Es el criterio duro de esta familia."""

    def test_todas_las_credenciales_del_corpus_se_detectan(self):
        for frase in CREDENCIALES:
            with self.subTest(frase=frase):
                self.assertTrue(
                    _secretos(frase), f"se escapo una credencial completa: {frase}"
                )

    def test_se_detectan_como_secreto_y_no_como_otra_cosa(self):
        # La categoria decide la accion: `secret` bloquea, `pii` solo advierte.
        # Detectar una contrasena y dejarla salir seria peor que no verla.
        for frase in CREDENCIALES:
            with self.subTest(frase=frase):
                categorias = {f.category for f in scan(frase)}
                self.assertIn("secret", categorias)

    def test_la_evidencia_no_lleva_la_contrasena(self):
        hallazgos = scan("Entra con el usuario admin y la clave Temporal#2026 al panel")
        for hallazgo in hallazgos:
            with self.subTest(regla=hallazgo.rule_id):
                self.assertNotIn("Temporal#2026", hallazgo.evidence)


class TestSinVerboEntreLaPalabraYElValor(unittest.TestCase):
    """La regla vieja pedia "la contrasena ES x". La mitad de las frases no lo dicen."""

    def test_la_clave_pegada_al_valor(self):
        self.assertIn(
            "credencial_en_espanol_sin_verbo",
            _secretos("Entra con el usuario admin y la clave Temporal#2026 al panel"),
        )

    def test_un_par_usuario_barra_clave(self):
        self.assertIn(
            "credencial_en_espanol_sin_verbo",
            _secretos("El acceso al FTP es aegis / Sup3rS3cret, no lo cambies todavia"),
        )

    def test_despues_de_dos_puntos(self):
        self.assertTrue(
            _secretos("Guarda esta credencial del correo corporativo: Mktg2026Flash")
        )

    def test_una_clave_de_baja_entropia_igual_se_ve(self):
        # `Sup3rS3cret` no pasa looks_random y es una contrasena de manual: si el
        # criterio fuera solo la entropia, esta se escaparia.
        self.assertFalse(looks_random("Sup3rS3cret"))
        self.assertTrue(parece_contrasena("Sup3rS3cret"))


class TestLoQueNoPuedeBloquear(unittest.TestCase):
    """Los negativos. Cada uno de estos rompio una version de la regla."""

    def test_ninguna_frase_de_trabajo_normal_dispara_un_secreto(self):
        for frase in NORMAL:
            with self.subTest(frase=frase):
                self.assertEqual(
                    _secretos(frase), [], f"falso bloqueo sobre trabajo legitimo: {frase}"
                )

    def test_codigo_que_llama_a_una_funcion_no_es_una_credencial(self):
        # Lo que un desarrollador pega diez veces por dia. Entraba como
        # incidente critico por generic_secret_assignment.
        self.assertEqual(_secretos("const password = hashPassword(input.value)"), [])

    def test_una_clave_primaria_no_es_un_secreto(self):
        # "Clave" en espanol son dos cosas. Esta entraba por credencial_en_espanol.
        self.assertEqual(_secretos("La clave primaria de la tabla es usuarios_2024_id"), [])

    def test_una_clave_publica_no_es_un_secreto(self):
        self.assertEqual(
            _secretos("La clave publica del servidor cambia con cada despliegue automatico"),
            [],
        )

    def test_una_norma_citada_cerca_de_la_palabra_credencial(self):
        # Entraba cuando la ventana entre la palabra y el valor era de 30
        # caracteres. Ahora son 24, que es lo que separa esto de una fuga real.
        self.assertEqual(
            _secretos("La credencial se rota cada 90 dias segun la ISO27001_v3 del area"),
            [],
        )

    def test_un_nombre_de_plan_no_es_una_contrasena(self):
        # Entraba con el largo minimo en 8. Ahora son 10.
        self.assertEqual(_secretos("El acceso de invitados usa el plan Free2024 sin costo"), [])

    def test_una_version_de_dependencia_no_es_una_contrasena(self):
        self.assertEqual(
            _secretos("Instala el paquete con pip install django-allauth==0.57.0 para el login"),
            [],
        )

    def test_un_marcador_de_plantilla_no_es_una_contrasena(self):
        self.assertEqual(
            _secretos("Documenta el acceso a la API REST usando Bearer <TOKEN_AQUI>"), []
        )


class TestLosValidadores(unittest.TestCase):
    """Los dos criterios de forma, sueltos, porque son los que se van a tocar."""

    def test_parece_contrasena_pide_largo_minimo(self):
        self.assertFalse(parece_contrasena("Corta1#"))
        self.assertTrue(parece_contrasena("Temporal#2026"))

    def test_parece_contrasena_rechaza_marcado(self):
        # Un fragmento entre comillas invertidas bloqueo una sesion entera de
        # Claude Code. No puede volver a pasar.
        self.assertFalse(parece_contrasena("`mi_password_2026`"))

    def test_una_llamada_a_funcion_es_codigo(self):
        self.assertTrue(parece_expresion_de_codigo("hashPassword(input.value)"))

    def test_base64_no_es_codigo(self):
        # Los secretos de verdad usan +, / y = y no pueden caer en este filtro.
        self.assertFalse(parece_expresion_de_codigo("dGVzdC1zZWNyZXQ="))
        self.assertFalse(parece_expresion_de_codigo("AKIAIOSFODNN7EXAMPLE"))


class TestElCorpusMideLoQueDice(unittest.TestCase):
    """Si el corpus se achica sin querer, estas pruebas dejan de probar algo."""

    def test_hay_negativos_suficientes_para_sostener_una_regla_que_bloquea(self):
        self.assertGreaterEqual(len(TRAMPAS_DE_CREDENCIAL), 15)

    def test_las_trampas_estan_dentro_del_corpus_normal(self):
        for frase in TRAMPAS_DE_CREDENCIAL:
            with self.subTest(frase=frase):
                self.assertIn(frase, NORMAL)


class TestElJsonNoPuedeFabricarCredenciales(unittest.TestCase):
    """El escape del JSON le mete digitos a las palabras y eso bloqueaba sesiones.

    El prompt viaja dentro de un JSON, donde "explicitamente" se escribe
    `expl\u00edcitamente`. Ese escape le agrega digitos y letras a una palabra
    espanola corriente y la vuelve indistinguible de una contrasena. Cuando cae
    cerca de la palabra "usuario" -- por ejemplo en el archivo de memoria que un
    CLI manda en cada request -- bloqueaba la sesion entera con un 403.

    Paso en vivo, con una sesion de Claude Code que solo pedia "revisa la
    carpeta". El agente que protege no puede volverse el que impide trabajar.
    """

    def _bloquea(self, texto_sistema: str, prompt: str) -> list[str]:
        cuerpo = json.dumps(
            {"system": texto_sistema, "messages": [{"role": "user", "content": prompt}]}
        ).encode()
        return [f.rule_id for f in scan_payload(cuerpo).findings]

    def test_una_palabra_acentuada_cerca_de_usuario_no_es_una_credencial(self):
        sistema = (
            "- [Cuenta git](feedback.md) - Usar cuenta juanMCanchala por defecto "
            "en este alias; solo usar webflash si el usuario lo pide explicitamente."
        ).replace("explicitamente", "explícitamente")
        self.assertEqual(self._bloquea(sistema, "revisa la carpeta"), [])

    def test_un_texto_largo_en_espanol_con_tildes_no_dispara_nada(self):
        sistema = (
            "El usuario prefiere que la documentacion este en espanol. "
            "La configuracion se hace explicitamente en el archivo de configuracion. "
            "El acceso al panel se documenta en la seccion correspondiente."
        )
        # Con las tildes de verdad, que es como se escribe.
        sistema = sistema.replace("configuracion", "configuración")
        sistema = sistema.replace("documentacion", "documentación")
        sistema = sistema.replace("seccion", "sección")
        self.assertEqual(self._bloquea(sistema, "hola"), [])

    def test_una_credencial_de_verdad_dentro_del_json_si_se_ve(self):
        # Lo de arriba no puede haberse pagado con dejar de detectar.
        self.assertTrue(
            self._bloquea("", "Entra con el usuario admin y la clave Temporal#2026")
        )


class TestElEspanolConTildes(unittest.TestCase):
    """"Contrasena" se escribe "contrasena", con ene. Ninguna regla la veia asi.

    Las reglas estan escritas sin diacriticos y el corpus tambien, asi que la
    cobertura se veia perfecta y la palabra mas importante del idioma para este
    producto pasaba de largo. No era una evasion: era la ortografia.
    """

    def _hallazgos(self, prompt: str) -> list[str]:
        cuerpo = json.dumps({"messages": [{"role": "user", "content": prompt}]}).encode()
        return [f.rule_id for f in scan_payload(cuerpo).findings]

    def test_contrasena_con_enie_se_detecta(self):
        self.assertTrue(
            self._hallazgos("La contraseña del servidor de producción es Verano2026Bogota")
        )

    def test_clave_con_valor_acentuado_se_detecta(self):
        self.assertTrue(self._hallazgos("Guarda la contraseña: Bogotá#2026Aegis"))

    def test_una_frase_normal_con_tildes_no_se_marca(self):
        self.assertEqual(
            self._hallazgos("Ayúdame a escribir el resumen de la reunión de mañana"),
            [],
        )


class TestLaCedulaDichaEnUnaFrase(unittest.TestCase):
    """El dato personal mas comun de Colombia, escrito como se escribe.

    La regla exigia el numero pegado a la palabra ("cedula: 1020345678"), y en
    espanol casi nunca lo esta: "mi numero de cedula ES 1.020.345.678". Con
    adyacencia obligatoria no se veia ninguna de las dos formas naturales.
    """

    def _hallazgos(self, prompt: str) -> list[str]:
        cuerpo = json.dumps({"messages": [{"role": "user", "content": prompt}]}).encode()
        return [f.rule_id for f in scan_payload(cuerpo).findings]

    def test_con_verbo_en_el_medio(self):
        self.assertIn("latam_national_id", self._hallazgos("Mi numero de cedula es 1.020.345.678"))

    def test_con_un_complemento_en_el_medio(self):
        self.assertIn("latam_national_id", self._hallazgos("La cedula del cliente es 79.482.113"))

    def test_pegada_como_antes(self):
        self.assertIn("latam_national_id", self._hallazgos("cedula: 1020345678"))

    def test_el_nit_de_una_empresa(self):
        self.assertIn("latam_national_id", self._hallazgos("El NIT de la empresa es 900.123.456-7"))

    def test_con_tilde_como_se_escribe(self):
        self.assertIn(
            "latam_national_id", self._hallazgos("Mi número de cédula es 1.020.345.678")
        )

    def test_un_numero_de_documento_administrativo_no_es_una_cedula(self):
        # "documento" es palabra comun y se quedo pegada al numero a proposito.
        self.assertEqual(self._hallazgos("Adjunto el documento 2024-15 del contrato"), [])

    def test_una_norma_no_es_una_cedula(self):
        self.assertEqual(self._hallazgos("El documento ISO 9001-2015 aplica a toda la empresa"), [])

    def test_hablar_de_la_cedula_sin_dar_ninguna(self):
        self.assertEqual(
            self._hallazgos("La cedula de ciudadania es un documento oficial en Colombia"), []
        )


if __name__ == "__main__":
    unittest.main()
