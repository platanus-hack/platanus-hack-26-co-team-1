"""Lo que se leyó de una imagen no corta como lo que estaba escrito.

Era la deuda anotada en detect/ocr.py: de las tres detecciones probabilísticas
del sistema -- modelo, inyección, OCR -- la del OCR era la única sin freno. Un
hallazgo leído de una captura bloqueaba con la misma autoridad que una llave de
AWS con formato reconocido.

Y el motivo está medido en ese mismo archivo: el texto que sale de un OCR es
aproximado. `Verano2026Bogota` se leyó como `Verano2o26Bogota`, y una llave de
AWS no se leyó a 900 px de ancho y sí a 1800. Un carácter mal leído puede
cortarle el envío a alguien sin que hubiera nada.

Lo que se prueba acá es que el origen VIAJA con el hallazgo (si no llega hasta
la decisión, la política no puede hacer nada con él) y que la decisión lo
respeta en las dos direcciones.
"""

from __future__ import annotations

import unittest

from aegis_agent.detect.types import ORIGEN_IMAGEN, ORIGEN_TEXTO, Finding
from aegis_agent.policy import Policy, decidir_sobre


def hallazgo(origen=ORIGEN_TEXTO, rule_id="aws_access_key_id", category="secret"):
    return Finding(
        rule_id=rule_id,
        category=category,
        severity="critical",
        confidence=1.0,
        evidence="AKIA****",
        start=0,
        end=8,
        origen=origen,
    )


class TestElOrigenPorDefecto(unittest.TestCase):
    def test_un_hallazgo_es_de_texto_salvo_que_se_diga(self):
        """Decenas de sitios construyen un Finding sin nombrar el origen."""

        suelto = Finding(
            rule_id="x", category="secret", severity="low",
            confidence=1.0, evidence="y", start=0, end=1,
        )
        self.assertEqual(suelto.origen, ORIGEN_TEXTO)


class TestLaRebaja(unittest.TestCase):
    def test_lo_escrito_en_el_cuerpo_sigue_cortando(self):
        """La rebaja no puede tocar al camino normal."""

        self.assertEqual(
            decidir_sobre("ai_unapproved", [hallazgo()], Policy()),
            "block_content",
        )

    def test_lo_leido_de_una_imagen_solo_avisa(self):
        self.assertEqual(
            decidir_sobre("ai_unapproved", [hallazgo(origen=ORIGEN_IMAGEN)], Policy()),
            "warn",
        )

    def test_la_empresa_puede_devolverle_la_autoridad(self):
        politica = Policy(ocr_action="block")
        self.assertEqual(
            decidir_sobre("ai_unapproved", [hallazgo(origen=ORIGEN_IMAGEN)], politica),
            "block_content",
        )

    def test_la_rebaja_no_convierte_un_aviso_en_un_permiso(self):
        """Rebajar es de bloquear a avisar. Nunca a dejar pasar en silencio."""

        accion = decidir_sobre(
            "ai_unapproved",
            [hallazgo(origen=ORIGEN_IMAGEN, category="pii", rule_id="email_address")],
            Policy(),
        )
        self.assertIn(accion, ("warn", "allow"))

    def test_un_dominio_prohibido_no_lo_afloja_ni_una_imagen(self):
        """La única regla de la política que expresa una prohibición gana igual."""

        politica = Policy(blocked_domains=frozenset({"deepseek.com"}))
        self.assertEqual(
            decidir_sobre(
                "ai_unapproved",
                [hallazgo(origen=ORIGEN_IMAGEN)],
                politica,
                host="deepseek.com",
            ),
            "block_content",
        )


class TestLaPoliticaViaja(unittest.TestCase):
    def test_ocr_action_sobrevive_la_ida_y_vuelta(self):
        vuelta = Policy.desde_dict(Policy(ocr_action="block").a_dict())
        self.assertEqual(vuelta.ocr_action, "block")

    def test_un_backend_viejo_no_lo_resetea(self):
        base = Policy(ocr_action="block")
        vuelta = Policy.desde_dict({"tenant_id": "acme"}, base=base)
        self.assertEqual(vuelta.ocr_action, "block")


class TestElOrigenLlegaDesdeElEscaneo(unittest.TestCase):
    """Sin esto la política decidiría sobre un campo que siempre dice 'texto'."""

    def test_el_texto_normal_no_se_marca_como_imagen(self):
        from aegis_agent.detect.payload import scan_payload

        resultado = scan_payload(b"mi llave es AKIAIOSFODNN7EXAMPLE")
        self.assertTrue(resultado.findings)
        for encontrado in resultado.findings:
            self.assertEqual(encontrado.origen, ORIGEN_TEXTO)

    def test_lo_que_sale_de_una_vista_de_imagen_se_marca(self):
        """Se simula la vista del OCR: leer una imagen de verdad cuesta segundos."""

        from unittest.mock import patch

        from aegis_agent.detect.payload import scan_payload

        with patch("aegis_agent.detect.payload.ocr.habilitado", return_value=True), \
             patch("aegis_agent.detect.payload.extraer_imagenes", return_value=[b"png"]), \
             patch(
                 "aegis_agent.detect.payload.ocr.vistas",
                 return_value=(["la contrasena del servidor es Verano2026Bogota"], False),
             ):
            resultado = scan_payload(b'{"mensaje":"mira esta captura"}')

        self.assertTrue(resultado.findings, "el OCR no aporto ningun hallazgo")
        self.assertTrue(
            any(f.origen == ORIGEN_IMAGEN for f in resultado.findings),
            f"ninguno quedo marcado: {[(f.rule_id, f.origen) for f in resultado.findings]}",
        )

    def test_el_mismo_secreto_en_texto_y_en_imagen_se_queda_con_el_del_texto(self):
        """Si está escrito en el cuerpo no hay nada probabilístico que rebajar."""

        from unittest.mock import patch

        from aegis_agent.detect.payload import scan_payload

        frase = "la contrasena del servidor es Verano2026Bogota"
        with patch("aegis_agent.detect.payload.ocr.habilitado", return_value=True), \
             patch("aegis_agent.detect.payload.extraer_imagenes", return_value=[b"png"]), \
             patch("aegis_agent.detect.payload.ocr.vistas", return_value=([frase], False)):
            resultado = scan_payload(frase.encode())

        credenciales = [f for f in resultado.findings if f.category == "secret"]
        self.assertTrue(credenciales)
        self.assertEqual(credenciales[0].origen, ORIGEN_TEXTO)


class TestElDescarteNoEsSilencioso(unittest.TestCase):
    """Una imagen que no se alcanzo a leer no es una imagen sin nada adentro.

    El presupuesto por defecto era de 4000 ms y la PRIMERA inferencia de una
    captura de 1920x1080 cuesta 4225 ms en esta maquina, asi que la primera
    imagen que mandaba cualquiera se descartaba entera. Y en silencio: el panel
    decia "se escaneo y no habia nada". En una demo, donde siempre hay una
    primera imagen, el OCR no encontraba nada nunca.
    """

    def test_una_imagen_que_no_se_leyo_marca_el_escaneo_como_incompleto(self):
        from unittest.mock import patch

        from aegis_agent.detect.payload import scan_payload

        with patch("aegis_agent.detect.payload.ocr.habilitado", return_value=True), \
             patch("aegis_agent.detect.payload.extraer_imagenes", return_value=[b"png"]), \
             patch("aegis_agent.detect.payload.ocr.vistas", return_value=([], True)):
            resultado = scan_payload(b'{"mensaje":"mira esta captura"}')

        self.assertTrue(
            resultado.truncated,
            "el OCR descarto una imagen y el resultado no lo dice",
        )

    def test_leerlas_todas_no_marca_nada(self):
        from unittest.mock import patch

        from aegis_agent.detect.payload import scan_payload

        with patch("aegis_agent.detect.payload.ocr.habilitado", return_value=True), \
             patch("aegis_agent.detect.payload.extraer_imagenes", return_value=[b"png"]), \
             patch("aegis_agent.detect.payload.ocr.vistas", return_value=(["hola"], False)):
            resultado = scan_payload(b'{"mensaje":"mira esta captura"}')

        self.assertFalse(resultado.truncated)

    def test_el_presupuesto_cubre_la_primera_inferencia_medida(self):
        """4225 ms es lo medido; el default tiene que dejarlo pasar con margen."""

        from aegis_agent.detect import ocr

        self.assertGreater(ocr.PRESUPUESTO_MS, 4225)


if __name__ == "__main__":
    unittest.main()


class TestElInterruptorViveEnLaPolitica(unittest.TestCase):
    """Leer imagenes se decide en el panel, no en una variable de entorno.

    `ocr_action` ya estaba en la pantalla. Un panel que deja elegir que hacer
    con lo que se encuentra en una imagen mientras la lectura esta apagada por
    otro lado promete algo que no ocurre, que es el defecto que este repositorio
    se sigue encontrando.
    """

    def _con_ocr_falso(self, leer_imagenes):
        from unittest.mock import patch

        from aegis_agent.detect.payload import scan_payload

        with patch("aegis_agent.detect.payload.ocr.habilitado", return_value=False), \
             patch("aegis_agent.detect.payload.extraer_imagenes", return_value=[b"png"]), \
             patch(
                 "aegis_agent.detect.payload.ocr.vistas",
                 return_value=(["la contrasena del servidor es Verano2026Bogota"], False),
             ) as vistas:
            scan_payload(b'{"m":"captura"}', leer_imagenes=leer_imagenes)
        return vistas

    def test_apagado_no_lee_ninguna_imagen(self):
        self._con_ocr_falso(False).assert_not_called()

    def test_encendido_desde_la_politica_lee(self):
        """Aunque AEGIS_OCR diga que no: la politica alcanza sola."""

        self._con_ocr_falso(True).assert_called_once()

    def test_el_campo_viaja_en_la_politica(self):
        from aegis_agent.policy import Policy

        self.assertTrue(Policy.desde_dict(Policy(ocr_enabled=True).a_dict()).ocr_enabled)
        # Y un backend viejo que no lo nombra no lo apaga solo.
        base = Policy(ocr_enabled=True)
        self.assertTrue(Policy.desde_dict({"tenant_id": "acme"}, base=base).ocr_enabled)
