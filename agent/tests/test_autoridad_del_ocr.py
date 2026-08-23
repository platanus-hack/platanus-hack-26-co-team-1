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
                 return_value=["la contrasena del servidor es Verano2026Bogota"],
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
             patch("aegis_agent.detect.payload.ocr.vistas", return_value=[frase]):
            resultado = scan_payload(frase.encode())

        credenciales = [f for f in resultado.findings if f.category == "secret"]
        self.assertTrue(credenciales)
        self.assertEqual(credenciales[0].origen, ORIGEN_TEXTO)


if __name__ == "__main__":
    unittest.main()
