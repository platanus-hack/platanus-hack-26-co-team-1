"""Los caracteres que se dibujan igual, el hexadecimal, y el PDF de verdad.

Tres huecos que midio la auditoria del 22-ago-2026 sobre la misma llave de AWS
escrita de doce formas distintas: pasaban seis.

El caso que mas importa de este archivo es el del ancho cero, y no por la razon
obvia. **No requiere un atacante.** Un caracter de ancho cero o un guion suave
aparecen solos al copiar de una pagina web, de un PDF o de Confluence: es a la
vez el vector de evasion mas barato Y una fuente de falsos negativos
accidentales.
"""

from __future__ import annotations

import json
import unittest
import zlib

from aegis_agent.detect.payload import scan_payload, vista_normalizada

SECRETO = "AKIAIOSFODNN7EXAMPLE"


def reglas(cuerpo) -> set[str]:
    if isinstance(cuerpo, str):
        cuerpo = cuerpo.encode("utf-8")
    return {f.rule_id for f in scan_payload(cuerpo).findings}


def como_prompt(texto: str) -> str:
    """Con ensure_ascii, que es como viaja de verdad.

    Es la parte que hace no trivial a este test: el cuerpo llega como JSON
    ASCII, asi que un caracter de ancho cero viaja escrito como los seis
    caracteres "\\u200b" y solo se vuelve invisible DESPUES de deshacer el
    escape. Normalizando unicamente el texto original, la evasion pasaba igual.
    """

    return json.dumps({"messages": [{"role": "user", "content": texto}]})


class TestInvisibles(unittest.TestCase):
    def test_ancho_cero_adentro_del_secreto(self):
        partido = "AKIA\u200bIOSFODNN7EXAMPLE"
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"mi llave es {partido}")))

    def test_guion_suave_adentro_del_secreto(self):
        partido = "AKIAIOSF­ODNN7EXAMPLE"
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"mi llave es {partido}")))

    def test_varios_invisibles_a_la_vez(self):
        partido = "A\u200bK‌I‍A⁠IOSFODNN7EXAMPLE"
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"llave: {partido}")))


class TestHomoglifos(unittest.TestCase):
    def test_a_cirilica(self):
        # U+0410 se dibuja igual que la A latina y es otra letra.
        homoglifo = "AKIАIOSFODNN7EXAMPLE"
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"mi llave es {homoglifo}")))

    def test_o_griega(self):
        homoglifo = "AKIAIΟSFODNN7EXAMPLE"
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"mi llave es {homoglifo}")))

    def test_la_normalizacion_no_toca_el_espanol(self):
        """Lo que no puede hacer: cambiar texto legitimo en otro idioma.

        Si la tabla de homoglifos se pasa de ancha, empieza a reescribir texto
        real --un nombre ruso, una formula griega-- y eso ensucia todo lo demas.
        """

        for texto in (
            "explicame que significa la letra sigma en estadistica",
            "el apellido del cliente es Chekhov",
            "la constante pi vale 3.14159",
        ):
            with self.subTest(texto=texto):
                self.assertEqual(vista_normalizada(texto), texto)


class TestHexadecimal(unittest.TestCase):
    def test_el_secreto_en_hex(self):
        hexeado = SECRETO.encode().hex()
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"valor: {hexeado}")))

    def test_hex_con_separadores(self):
        hexeado = ":".join(f"{b:02x}" for b in SECRETO.encode())
        self.assertIn("aws_access_key_id", reglas(como_prompt(f"dump: {hexeado}")))

    def test_un_hash_no_genera_ruido(self):
        """Un binario decodificado es ruido que cuesta una pasada de reglas.

        Por eso la vista se descarta si lo que sale no es texto, y el umbral es
        alto: un sha256 en hex decodifica a bytes sin sentido.
        """

        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        self.assertEqual(reglas(como_prompt(f"el hash del archivo es {sha}")), set())


class TestPdf(unittest.TestCase):
    """El motor abria los .docx porque son zips. Un PDF no es un zip."""

    TEXTO = b"BT /F1 12 Tf (La contrasena del servidor de produccion es Verano2026Bogota) Tj ET"

    def _pdf(self, cuerpo: bytes, filtro: bytes = b"") -> bytes:
        return (
            b"%PDF-1.4\n4 0 obj<</Length "
            + str(len(cuerpo)).encode()
            + filtro
            + b">>stream\n"
            + cuerpo
            + b"\nendstream endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
        )

    def test_pdf_con_flatedecode(self):
        """El que produce Word, Google Docs y LaTeX. Era invisible."""

        pdf = self._pdf(zlib.compress(self.TEXTO), b"/Filter/FlateDecode")
        self.assertIn("credencial_en_espanol", reglas(pdf))

    def test_pdf_sin_comprimir_sigue_funcionando(self):
        self.assertIn("credencial_en_espanol", reglas(self._pdf(self.TEXTO)))

    def test_pdf_adjunto_en_un_multipart(self):
        pdf = self._pdf(zlib.compress(self.TEXTO), b"/Filter/FlateDecode")
        cuerpo = (
            b'--x\r\nContent-Disposition: form-data; name="file"; '
            b'filename="propuesta.pdf"\r\n\r\n' + pdf
        )
        self.assertIn("credencial_en_espanol", reglas(cuerpo))

    def test_el_valor_no_se_traga_el_parentesis(self):
        """La regresion que encontro la sonda del PDF, y que no vio el trinquete.

        El texto de un PDF va entre parentesis, asi que la regla capturaba
        "Verano2026Bogota)" con el cierre pegado y el validador lo descartaba por
        parecer una llamada a funcion. La credencial estaba ahi y no se veia.

        El corpus del banco no tenia ni un valor entre delimitadores, y por eso
        el trinquete quedo en verde mientras esto estaba roto. Vale como
        recordatorio de que un trinquete protege lo que el corpus contiene.
        """

        for delimitado in (
            "(la clave es Verano2026Bogota)",
            "[la clave es Verano2026Bogota]",
            "{la clave es Verano2026Bogota}",
            "la clave es Verano2026Bogota;",
            "la clave es Verano2026Bogota, avisame",
        ):
            with self.subTest(delimitado=delimitado):
                self.assertIn(
                    "credencial_en_espanol",
                    reglas(como_prompt(delimitado)),
                    f"no vio la credencial en {delimitado!r}",
                )


class TestLoQueQuedaFuera(unittest.TestCase):
    """Documenta la frontera, para que nadie la tome por un olvido.

    rot13, el texto invertido, base32 y base85 NO se cubren. Esa lista no termina
    nunca, y cada vista nueva es una pasada completa de reglas sobre todo el
    cuerpo, o sea latencia en el camino critico de cada envio. La frontera
    elegida: se cubre lo que aparece solo o por herramientas normales, y un
    adversario que codifica adrede queda fuera del alcance de T1.

    Si algun dia se decide cubrirlos, este test se da vuelta a proposito.
    """

    def test_rot13_no_se_cubre_y_es_deliberado(self):
        rot13 = SECRETO.translate(
            str.maketrans(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm",
            )
        )
        self.assertEqual(reglas(como_prompt(f"valor: {rot13}")), set())

    def test_invertido_no_se_cubre_y_es_deliberado(self):
        self.assertEqual(reglas(como_prompt(f"al reves: {SECRETO[::-1]}")), set())


if __name__ == "__main__":
    unittest.main()
