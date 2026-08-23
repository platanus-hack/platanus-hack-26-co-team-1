"""El OCR fuera del camino critico: se lee al subir, se cobra al enviar.

## Que se prueba y por que importa el orden

El OCR estaba apagado por defecto porque cuesta entre 1,7 y 9 segundos y eso se
pagaba en el momento en que la persona aprieta enviar. La ventana que lo
resuelve es que **subir el archivo y pedirle al modelo que lo lea son dos
requests distintos**, y entre los dos la persona todavia tiene que escribir.

De ahi salen las dos mitades de este archivo, y las dos tienen que valer o la
funcion no sirve:

1. **La proteccion no se afloja.** Lo que se subio se lee, y el turno siguiente
   se corta si la imagen traia algo. Que el archivo ya este en el blob no es una
   fuga: nadie lo mira hasta que alguien le pide al modelo que lo lea.
2. **La latencia se fue de verdad.** El request de la subida no espera la
   lectura. Si esta mitad se rompe, lo unico que hicimos fue mover el problema.

El motor de OCR es falso en todos los casos, igual que en
`test_ocr_de_imagenes.py`: lo que se prueba es la cañeria, no la calidad de la
lectura, que ya esta medida y anotada en `detect/ocr.py`.
"""

from __future__ import annotations

import json
import struct
import threading
import time
import unittest
import zlib
from dataclasses import replace
from unittest.mock import patch

from aegis_agent import adjuntos
from aegis_agent.detect import ocr
from aegis_agent.detect.payload import scan_payload


def png(ancho: int = 1, alto: int = 1) -> bytes:
    def trozo(tipo: bytes, datos: bytes) -> bytes:
        cuerpo = tipo + datos
        return struct.pack(">I", len(datos)) + cuerpo + struct.pack(">I", zlib.crc32(cuerpo))

    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\xff\xff\xff" * ancho)
    return b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", ihdr) + trozo(b"IDAT", idat) + trozo(b"IEND", b"")


PNG = png()
CON_SECRETO = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
SIN_NADA = "grafico de ventas del trimestre"


def _escanear(texto: str) -> list:
    return scan_payload(texto.encode("utf-8")).findings


class Base(unittest.TestCase):
    def setUp(self):
        adjuntos.olvidar_todo()
        self.addCleanup(adjuntos.olvidar_todo)
        # `registrar` no hace nada con el OCR apagado, que es el default.
        parche = patch.object(ocr, "habilitado", return_value=True)
        parche.start()
        self.addCleanup(parche.stop)

    def _leyendo(self, texto: str, tarda: float = 0.0):
        """Un motor de OCR falso que tarda lo que se le diga."""

        def vistas(imagenes):
            if tarda:
                time.sleep(tarda)
            return ([texto], False)

        return patch.object(ocr, "vistas", side_effect=vistas)


class TestLaProteccionNoSeAfloja(Base):
    """Mover el OCR de lugar no puede significar dejar pasar la fuga."""

    def test_lo_que_se_subio_se_lee_y_se_cobra_en_el_turno(self):
        with self._leyendo(CON_SECRETO):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            hallazgos, incompleto = adjuntos.cobrar("chatgpt.com")

        self.assertEqual([f.rule_id for f in hallazgos], ["aws_access_key_id"])
        self.assertFalse(incompleto)

    def test_una_imagen_limpia_no_inventa_nada(self):
        with self._leyendo(SIN_NADA):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            hallazgos, _ = adjuntos.cobrar("chatgpt.com")
        self.assertEqual(hallazgos, [])

    def test_el_turno_espera_a_la_lectura_que_todavia_corre(self):
        """El caso de quien sube y aprieta enviar de inmediato.

        No dejarlo pasar seria mentir sobre la proteccion. Se espera, con
        presupuesto: en el peor caso se paga una parte del OCR, nunca todo.
        """

        with self._leyendo(CON_SECRETO, tarda=0.3):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            hallazgos, _ = adjuntos.cobrar("chatgpt.com", espera_ms=3000)

        self.assertEqual([f.rule_id for f in hallazgos], ["aws_access_key_id"])

    def test_si_se_agota_el_presupuesto_el_escaneo_queda_marcado_incompleto(self):
        """El envio pasa, pero quien decide tiene que saber que no se vio todo.

        Es la misma senal que da un payload truncado, y no es un detalle: la
        alternativa --decir que el escaneo fue completo-- convierte un timeout
        en una promesa falsa.
        """

        with self._leyendo(CON_SECRETO, tarda=5):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            hallazgos, incompleto = adjuntos.cobrar("chatgpt.com", espera_ms=50)

        self.assertEqual(hallazgos, [])
        self.assertTrue(incompleto)

    def test_lo_subido_a_una_ia_no_lo_cobra_otra(self):
        with self._leyendo(CON_SECRETO):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            ajenos, _ = adjuntos.cobrar("gemini.google.com")
        self.assertEqual(ajenos, [])
        self.assertTrue(adjuntos.hay_pendientes("chatgpt.com"))

    def test_varias_imagenes_en_una_subida_se_leen_todas(self):
        with self._leyendo(CON_SECRETO):
            leidas = adjuntos.registrar("chatgpt.com", PNG + PNG, "", _escanear)
            hallazgos, _ = adjuntos.cobrar("chatgpt.com")
        self.assertGreaterEqual(leidas, 1)
        self.assertTrue(hallazgos)


class TestLaLatenciaSeFue(Base):
    """La otra mitad. Sin esto solo movimos el problema de lugar."""

    def test_registrar_no_espera_la_lectura(self):
        """Lo que sostiene toda la funcion, medido y no supuesto.

        El OCR falso tarda un segundo entero. Si `registrar` devolviera despues
        de la lectura, la persona pagaria esa espera al soltar el archivo, que
        es justo lo que hacia antes.
        """

        with self._leyendo(CON_SECRETO, tarda=1.0):
            arranque = time.perf_counter()
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            demora = time.perf_counter() - arranque

            self.assertLess(demora, 0.25, "la subida esta pagando el OCR")
            # Y la lectura igual termina: no se perdio, se movio.
            hallazgos, _ = adjuntos.cobrar("chatgpt.com", espera_ms=5000)
            self.assertTrue(hallazgos)

    def test_con_el_ocr_apagado_no_se_registra_nada(self):
        """El default. Ni hilos, ni pendientes, ni costo."""

        with patch.object(ocr, "habilitado", return_value=False):
            with self._leyendo(CON_SECRETO) as falso:
                leidas = adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
        self.assertEqual(leidas, 0)
        falso.assert_not_called()
        self.assertFalse(adjuntos.hay_pendientes("chatgpt.com"))

    def test_sin_destino_no_hay_nada_que_registrar(self):
        """Sin `Origin` no se sabe de que conversacion es el archivo.

        Es el mismo limite que ya tiene `subidas.py`, y se arregla en el mismo
        lugar: la correlacion por proceso del ADR 0004.
        """

        with self._leyendo(CON_SECRETO):
            self.assertEqual(adjuntos.registrar("", PNG, "", _escanear), 0)


class TestLaHigieneDelEstado(Base):
    """Un pendiente que nadie cobra no puede quedar dando vueltas para siempre."""

    def test_cobrar_consume(self):
        """Si no, un hallazgo bloquearia todos los turnos siguientes.

        La persona sacaria el adjunto y no podria seguir la conversacion, sin
        ninguna forma de entender por que.
        """

        with self._leyendo(CON_SECRETO):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            primero, _ = adjuntos.cobrar("chatgpt.com")
            segundo, _ = adjuntos.cobrar("chatgpt.com")

        self.assertTrue(primero)
        self.assertEqual(segundo, [])

    def test_un_pendiente_viejo_se_olvida(self):
        """Quien adjunta, se arrepiente y saca el archivo antes de enviar."""

        with self._leyendo(CON_SECRETO):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            # -1 y no 0: la condicion es `> VIDA_MS`, asi que con 0 el test
            # exige que haya pasado tiempo ESTRICTAMENTE mayor que cero entre
            # registrar y cobrar. En Windows `time.time()` avanza de a ~15,6 ms,
            # asi que las dos llamadas caen seguido en el mismo tick, la resta
            # da 0.0 y `0 > 0` es falso: el pendiente no vence y el test falla.
            # Medido en main sin tocar nada: 1 de cada 5 corridas.
            with patch.object(adjuntos, "VIDA_MS", -1):
                hallazgos, _ = adjuntos.cobrar("chatgpt.com")

        self.assertEqual(hallazgos, [])

    def test_un_motor_que_revienta_no_deja_el_turno_colgado(self):
        """Fallar tiene que ser rapido y silencioso, no un candado."""

        with patch.object(ocr, "vistas", side_effect=RuntimeError("sin motor")):
            adjuntos.registrar("chatgpt.com", PNG, "", _escanear)
            arranque = time.perf_counter()
            hallazgos, _ = adjuntos.cobrar("chatgpt.com", espera_ms=3000)
            demora = time.perf_counter() - arranque

        self.assertEqual(hallazgos, [])
        self.assertLess(demora, 1.0)

    def test_no_se_leen_mas_de_las_permitidas_a_la_vez(self):
        """Arrastrar veinte imagenes no puede dejar el equipo de rodillas.

        Cada lectura ocupa un hilo y CPU, y es CPU que la persona esta usando
        para trabajar en ese mismo momento.
        """

        a_la_vez = 0
        tope = 0
        candado = threading.Lock()

        def vistas(imagenes):
            nonlocal a_la_vez, tope
            with candado:
                a_la_vez += 1
                tope = max(tope, a_la_vez)
            time.sleep(0.05)
            with candado:
                a_la_vez -= 1
            return ([SIN_NADA], False)

        with patch.object(ocr, "vistas", side_effect=vistas):
            adjuntos.registrar("chatgpt.com", PNG * 8, "", _escanear)
            adjuntos.cobrar("chatgpt.com", espera_ms=5000)

        self.assertLessEqual(tope, adjuntos.MAX_EN_VUELO)


class TestPorElAddonCompleto(Base):
    """El camino de verdad: dos requests, como en la vida real.

    Primero la subida al host de blobs --que no es una IA para el catalogo-- y
    despues el turno a la IA. Es el unico test que prueba que las dos mitades se
    encuentran: que lo que se registro con el `Origin` de la subida lo cobre el
    host del turno.
    """

    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path

        from tests.test_embudo import make_addon

        self.workdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.workdir.cleanup)
        self.addon = make_addon(Path(self.workdir.name) / "eventos.jsonl")
        self.addon.policy = replace(self.addon.policy, ocr_enabled=True)

    def _subir(self):
        from tests.test_embudo import FakeFlow, FakeRequest

        cuerpo = (
            b'--x\r\nContent-Disposition: form-data; name="file"; filename="captura.png"'
            b"\r\nContent-Type: image/png\r\n\r\n" + PNG
        )
        flow = FakeFlow(
            FakeRequest(
                "files.oaiusercontent.com",
                "/upload/abc",
                cuerpo,
                method="POST",
                headers={
                    "Content-Type": "multipart/form-data; boundary=x",
                    "Origin": "https://chatgpt.com",
                },
            )
        )
        self.addon.request(flow)
        return flow

    def _enviar(self):
        from tests.test_embudo import FakeFlow, FakeRequest

        cuerpo = json.dumps(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "que dice?"}]}
        ).encode()
        flow = FakeFlow(
            FakeRequest(
                "chatgpt.com",
                "/backend-api/conversation",
                cuerpo,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
        )
        self.addon.request(flow)
        return flow

    def test_la_captura_con_el_secreto_corta_el_turno_siguiente(self):
        """La funcion entera, en dos requests.

        La subida pasa --el archivo en el blob todavia no es una fuga-- y el
        turno que le pide al modelo que lo lea es el que se corta.
        """

        with self._leyendo(CON_SECRETO):
            subida = self._subir()
            self.assertIsNone(subida.response, "la subida no tenia que cortarse")

            turno = self._enviar()

        self.assertIsNotNone(turno.response, "el turno tenia que cortarse")
        self.assertEqual(turno.response.status_code, 403)

    def test_una_captura_limpia_deja_pasar_el_turno(self):
        with self._leyendo(SIN_NADA):
            self._subir()
            turno = self._enviar()
        self.assertIsNone(turno.response)

    def test_la_subida_no_paga_la_lectura(self):
        """Lo mismo que el test de latencia, pero por el addon completo.

        Aca es donde se veria si algo del camino --el escaneo del multipart, la
        clasificacion-- volvio a meter el OCR en el request de la subida.
        """

        with self._leyendo(CON_SECRETO, tarda=1.0):
            arranque = time.perf_counter()
            self._subir()
            demora = time.perf_counter() - arranque
            adjuntos.cobrar("chatgpt.com", espera_ms=5000)

        self.assertLess(demora, 0.35, "la subida esta pagando el OCR")
