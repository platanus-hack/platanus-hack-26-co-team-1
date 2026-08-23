"""El pantallazo, que era el hueco mas grande del motor.

Este archivo esta partido en dos mitades y la division es a proposito:

- **La plomeria** (extraer las imagenes del request) corre siempre. Es barata, no
  necesita ninguna dependencia y es donde estan los casos que se pueden romper
  sin darse cuenta.
- **El OCR** corre con un motor falso, porque el de verdad cuesta segundos. Hay un
  solo test en vivo y esta salteado salvo que se pida explicitamente.

Es la misma forma en que el repo trata a T2, y por el mismo motivo: una suite que
tarda minutos deja de correrse.
"""

from __future__ import annotations

import base64
import io
import json
import os
import struct
import unittest
import zlib
from unittest.mock import patch

from aegis_agent.detect import ocr
from aegis_agent.detect.imagenes import MAX_IMAGENES, es_imagen, extraer
from aegis_agent.detect.payload import scan_payload


def png(ancho: int = 1, alto: int = 1) -> bytes:
    """Un PNG valido y minimo. Lo que se prueba es la FORMA del envio."""

    def trozo(tipo: bytes, datos: bytes) -> bytes:
        cuerpo = tipo + datos
        return struct.pack(">I", len(datos)) + cuerpo + struct.pack(">I", zlib.crc32(cuerpo))

    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\xff\xff\xff" * ancho)
    return b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr) + trozo(b"IDAT", idat) + trozo(b"IEND", b"")


PNG = png()
B64 = base64.b64encode(PNG).decode()

CUERPO_OPENAI = json.dumps(
    {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "que dice este pantallazo?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
                ],
            }
        ],
    }
).encode()

CUERPO_ANTHROPIC = json.dumps(
    {
        "model": "claude-opus-4",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "resumime esto"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": B64},
                    },
                ],
            }
        ],
    }
).encode()

CUERPO_MULTIPART = (
    b'--x\r\nContent-Disposition: form-data; name="file"; filename="pantalla.png"'
    b"\r\nContent-Type: image/png\r\n\r\n" + PNG
)


class TestExtraerImagenes(unittest.TestCase):
    """La plomeria. Siempre corre y no cuesta nada."""

    def test_las_tres_formas_de_los_proveedores(self):
        casos = {
            "OpenAI image_url data:": CUERPO_OPENAI,
            "Anthropic bloque image": CUERPO_ANTHROPIC,
            "subida multipart": CUERPO_MULTIPART,
            "imagen cruda como body": PNG,
        }
        for nombre, cuerpo in casos.items():
            with self.subTest(forma=nombre):
                texto = cuerpo.decode("utf-8", errors="replace")
                self.assertTrue(extraer(cuerpo, texto), f"no encontro la imagen en {nombre}")

    def test_un_prompt_sin_imagen_no_devuelve_nada(self):
        """Lo que importa para el costo: sin imagen no se paga el OCR."""

        cuerpo = json.dumps({"messages": [{"content": "hola, como estas?"}]}).encode()
        self.assertEqual(extraer(cuerpo, cuerpo.decode()), [])

    def test_se_filtra_por_firma_y_no_por_el_nombre_de_la_clave(self):
        """Renombrar la clave no esconde la imagen.

        Se decodifica y se mira la firma, que es la misma decision que ya toma
        files.py: el cliente controla los nombres y los encabezados.
        """

        cuerpo = json.dumps({"cosas": [{"data": B64}]}).encode()
        self.assertTrue(extraer(cuerpo, cuerpo.decode()))

    def test_un_base64_que_no_es_imagen_se_descarta(self):
        basura = base64.b64encode(b"esto no es una imagen" * 10).decode()
        cuerpo = json.dumps({"data": basura}).encode()
        self.assertEqual(extraer(cuerpo, cuerpo.decode()), [])

    def test_la_misma_imagen_dos_veces_es_una(self):
        """El OCR cuesta demasiado para pagarlo dos veces por la misma imagen."""

        cuerpo = json.dumps(
            {"a": {"data": B64}, "b": {"url": "data:image/png;base64," + B64}}
        ).encode()
        self.assertEqual(len(extraer(cuerpo, cuerpo.decode())), 1)

    def test_hay_un_tope_de_imagenes(self):
        """Un cuerpo con cien miniaturas no puede costar cien veces el OCR."""

        muchas = [{"data": base64.b64encode(png(1, n + 1)).decode()} for n in range(40)]
        cuerpo = json.dumps({"content": muchas}).encode()
        self.assertLessEqual(len(extraer(cuerpo, cuerpo.decode())), MAX_IMAGENES)

    def test_es_imagen_reconoce_los_formatos_comunes(self):
        for firma in (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff\xe0", b"GIF89a", b"BM"):
            with self.subTest(firma=firma):
                self.assertTrue(es_imagen(firma + b"\x00" * 32))
        self.assertFalse(es_imagen(b"{\"hola\": 1}"))

    def test_un_json_roto_no_revienta(self):
        """El shadow AI sin catalogar tampoco tiene una forma conocida."""

        cuerpo = b'{"content": [{"data": "' + B64.encode() + b'"'  # sin cerrar
        self.assertTrue(extraer(cuerpo, cuerpo.decode()))


class TestJuntarPorRenglones(unittest.TestCase):
    """Sin esto se pierde el hallazgo por como el OCR corta las cajas.

    Medido con el motor de verdad: "NIT" y "900.123.456-7" salen como dos cajas
    distintas, y la regla de documento de identidad necesita que la palabra este
    CERCA del numero. El motor tenia razon y el detector no lo veia.
    """

    @staticmethod
    def caja(x: float, y: float, texto: str, conf: float = 0.9):
        return ([[x, y], [x + 50, y], [x + 50, y + 20], [x, y + 20]], texto, conf)

    def test_lo_que_esta_a_la_misma_altura_va_junto(self):
        cajas = [self.caja(200, 100, "900.123.456-7"), self.caja(20, 100, "NIT")]
        self.assertEqual(ocr._por_renglones(cajas), "NIT 900.123.456-7")

    def test_los_renglones_salen_en_orden_vertical(self):
        cajas = [self.caja(20, 200, "segunda"), self.caja(20, 20, "primera")]
        self.assertEqual(ocr._por_renglones(cajas), "primera\nsegunda")

    def test_se_descarta_la_caja_de_baja_confianza(self):
        cajas = [self.caja(20, 20, "seguro", 0.95), self.caja(20, 60, "adivinanza", 0.1)]
        self.assertEqual(ocr._por_renglones(cajas), "seguro")

    def test_tolera_cajas_con_forma_inesperada(self):
        ocr._por_renglones([([], "algo", "no-es-un-numero")])


class TestApagadoPorDefecto(unittest.TestCase):
    def test_esta_apagado_si_nadie_lo_prende(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AEGIS_OCR", None)
            self.assertFalse(ocr.habilitado())

    def test_apagado_no_paga_nada(self):
        """Con el OCR apagado, un pantallazo no dispara ni cuesta."""

        with patch.dict(os.environ, {"AEGIS_OCR": "0"}):
            with patch.object(ocr, "vistas") as falso:
                scan_payload(CUERPO_OPENAI)
                falso.assert_not_called()

    def test_sin_el_motor_instalado_devuelve_vacio_y_no_revienta(self):
        with patch.object(ocr, "cargar", return_value=None):
            self.assertEqual(ocr.leer(PNG), "")


class TestPorLaCascadaConMotorFalso(unittest.TestCase):
    """El texto del OCR tiene que entrar al motor como cualquier otra vista.

    Con motor falso a proposito: lo que se prueba es la cañeria, no la calidad de
    la lectura. La calidad se midio con el motor de verdad y esta anotada en
    detect/ocr.py.
    """

    TEXTO_LEIDO = (
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"
        "La contrasena del servidor es Verano2026Bogota\n"
        "cliente: Bancolombia NIT 900.123.456-7"
    )

    def _reglas(self, cuerpo: bytes) -> set[str]:
        with patch.dict(os.environ, {"AEGIS_OCR": "1"}):
            with patch.object(ocr, "vistas", return_value=([self.TEXTO_LEIDO], False)):
                return {f.rule_id for f in scan_payload(cuerpo).findings}

    def test_el_pantallazo_a_openai_ahora_se_ve(self):
        reglas = self._reglas(CUERPO_OPENAI)
        self.assertIn("aws_access_key_id", reglas)
        self.assertIn("credencial_en_espanol", reglas)
        self.assertIn("latam_national_id", reglas)

    def test_el_pantallazo_a_anthropic_ahora_se_ve(self):
        self.assertIn("credencial_en_espanol", self._reglas(CUERPO_ANTHROPIC))

    def test_la_captura_subida_como_archivo_ahora_se_ve(self):
        self.assertIn("credencial_en_espanol", self._reglas(CUERPO_MULTIPART))

    def test_un_ocr_que_devuelve_vacio_no_rompe_nada(self):
        with patch.dict(os.environ, {"AEGIS_OCR": "1"}):
            with patch.object(ocr, "vistas", return_value=([], True)):
                scan_payload(CUERPO_OPENAI)

    def test_un_ocr_que_revienta_no_se_lleva_puesto_el_escaneo(self):
        """El OCR es una vista mas, no el motor. Que falle no puede tumbar T1."""

        with patch.dict(os.environ, {"AEGIS_OCR": "1"}):
            with patch.object(ocr, "leer", side_effect=RuntimeError("boom")):
                cuerpo = json.dumps(
                    {
                        "messages": [
                            {
                                "content": [
                                    {"type": "text", "text": "mi llave es AKIAIOSFODNN7EXAMPLE"},
                                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + B64}},
                                ]
                            }
                        ]
                    }
                ).encode()
                try:
                    reglas = {f.rule_id for f in scan_payload(cuerpo).findings}
                except RuntimeError:
                    self.fail("una excepcion del OCR se llevo puesto el escaneo de T1")
                self.assertIn("aws_access_key_id", reglas)


@unittest.skipUnless(
    ocr.disponible() and os.environ.get("AEGIS_OCR_VIVO") == "1",
    "el motor de OCR cuesta segundos: se corre con AEGIS_OCR_VIVO=1",
)
class TestEnVivo(unittest.TestCase):
    """Con el motor de verdad. Salteado salvo que se pida.

    Lo que este test fija es el hallazgo mas importante de haber medido: **las
    reglas contextuales sobreviven al ruido del OCR y las de formato no.** Un
    caracter mal leido y la llave de AWS deja de matchear; "la contrasena ... es
    X" aguanta, porque le alcanza la forma de la frase.
    """

    def _captura(self) -> bytes:
        from PIL import Image, ImageDraw, ImageFont

        imagen = Image.new("RGB", (900, 260), "white")
        dibujo = ImageDraw.Draw(imagen)
        try:
            fuente = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 22)
        except OSError:
            fuente = ImageFont.load_default()
        for i, linea in enumerate(
            [
                "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
                "La contrasena del servidor es Verano2026Bogota",
                "cliente: Bancolombia  NIT 900.123.456-7",
            ]
        ):
            dibujo.text((20, 20 + i * 36), linea, fill="black", font=fuente)
        buffer = io.BytesIO()
        imagen.save(buffer, "PNG")
        return buffer.getvalue()

    def test_las_reglas_de_contexto_sobreviven_al_ruido(self):
        # El presupuesto se levanta a proposito. Este test mide CORRECCION --que
        # las reglas de contexto sobrevivan al ruido del OCR-- y no velocidad, y
        # con el presupuesto de produccion el resultado depende de cuan cargada
        # este la maquina: se cayo una vez por eso, justo despues de un rebase, y
        # parecio una regresion cuando era la CPU ocupada. Un test intermitente
        # en una suite de seguridad se termina borrando, y con el se va la unica
        # verificacion de que el OCR funciona de verdad.
        #
        # Que el presupuesto se respete se mide aparte, en el test de arriba que
        # usa motor falso, donde el tiempo no depende de nada externo.
        with patch.dict(os.environ, {"AEGIS_OCR": "1"}), patch.object(
            ocr, "PRESUPUESTO_MS", 120_000
        ):
            cuerpo = json.dumps(
                {
                    "messages": [
                        {
                            "content": [
                                {"type": "text", "text": "que dice esto?"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": "data:image/png;base64,"
                                        + base64.b64encode(self._captura()).decode()
                                    },
                                },
                            ]
                        }
                    ]
                }
            ).encode()
            reglas = {f.rule_id for f in scan_payload(cuerpo).findings}
        self.assertIn("credencial_en_espanol", reglas)
        self.assertIn("latam_national_id", reglas)


if __name__ == "__main__":
    unittest.main()
