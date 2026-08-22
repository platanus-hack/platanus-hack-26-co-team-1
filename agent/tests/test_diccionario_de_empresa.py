"""Los datos que solo esta empresa sabe que son suyos.

Una llave de AWS se reconoce por su formato, y el modelo local puede adivinar
que "Grupo Exito" es una empresa. Ninguno de los dos sabe que Grupo Exito es
*cliente de esta empresa*, ni que "Proyecto Fenix" es el nombre en clave de una
adquisicion que todavia no se anuncio. Eso lo sabe la empresa, y hasta aca no
tenia forma de decirlo.

Dos cosas se prueban aca, y la segunda importa mas de lo que parece:

  - Que los terminos declarados se detecten, incluso escondidos (gzip, base64,
    tildes). Si comprimir el cuerpo alcanzara para pasar el nombre de un
    cliente, la lista no serviria para nada.
  - Que **el termino nunca salga del equipo**. El diccionario es, por
    definicion, la lista mas sensible que tiene la empresa: nombres de clientes,
    proyectos sin anunciar, dominios internos. Si el panel dejara reconstruirla,
    Aegis seria el agujero que dice tapar.
"""

from __future__ import annotations

import base64
import gzip
import json
import unittest

from aegis_agent.detect import diccionario
from aegis_agent.detect.payload import scan_payload
from aegis_agent.lessons import lesson_for
from aegis_agent.policy import Policy, decidir_sobre

TERMINOS = {
    "Proyecto Fenix": "proyecto",
    "Bancolombia": "cliente",
    "intranet.acme.co": "dominio interno",
}


def _cuerpo(texto: str) -> bytes:
    return json.dumps({"messages": [{"role": "user", "content": texto}]}).encode()


class TestLoQueLaEmpresaDeclara(unittest.TestCase):
    def test_un_termino_declarado_se_detecta(self):
        hallazgos = diccionario.buscar("El contrato con Bancolombia vence en marzo", TERMINOS)
        self.assertEqual([h.rule_id for h in hallazgos], ["empresa_cliente"])

    def test_un_termino_de_varias_palabras(self):
        self.assertTrue(diccionario.buscar("Hablemos del Proyecto Fenix", TERMINOS))

    def test_no_distingue_mayusculas_ni_tildes(self):
        # Quien escribe la lista no tiene por que acordarse de las tres formas.
        for variante in ("proyecto fenix", "PROYECTO FENIX", "Proyecto Fénix"):
            with self.subTest(variante=variante):
                self.assertTrue(diccionario.buscar(f"sobre el {variante} de este ano", TERMINOS))

    def test_los_espacios_de_mas_no_lo_esconden(self):
        self.assertTrue(diccionario.buscar("el Proyecto   Fenix", TERMINOS))

    def test_un_dominio_interno_tambien_es_un_termino(self):
        hallazgos = diccionario.buscar("Mira intranet.acme.co/reportes", TERMINOS)
        self.assertEqual([h.rule_id for h in hallazgos], ["empresa_dominio_interno"])

    def test_la_misma_etiqueta_no_se_repite(self):
        hallazgos = diccionario.buscar("Bancolombia y otra vez Bancolombia", TERMINOS)
        self.assertEqual(len(hallazgos), 1)


class TestLoQueNoPuedeMarcar(unittest.TestCase):
    def test_sin_diccionario_no_marca_nada(self):
        self.assertEqual(diccionario.buscar("El contrato con Bancolombia", {}), [])

    def test_una_palabra_que_contiene_al_termino_no_cuenta(self):
        # Sin limite de palabra, un termino corto marca media conversacion.
        self.assertEqual(diccionario.buscar("hay que asegurar el envio", {"sura": "cliente"}), [])

    def test_los_terminos_cortos_se_descartan(self):
        # "SAP" o "IA" aparecen en cualquier conversacion: declararlos convierte
        # al panel en un generador de falsos positivos.
        self.assertEqual(diccionario.buscar("usamos SAP y IA", {"SAP": "sistema", "IA": "x"}), [])
        self.assertNotIn("sap", diccionario.utilizables({"SAP": "sistema"}))

    def test_una_frase_de_trabajo_normal_no_se_marca(self):
        for frase in (
            "Un proyecto cualquiera arranca en marzo",
            "Cuales son los principales bancos de Colombia?",
            "Necesito armar la intranet del equipo",
        ):
            with self.subTest(frase=frase):
                self.assertEqual(diccionario.buscar(frase, TERMINOS), [])


class TestElTerminoNoSaleDelEquipo(unittest.TestCase):
    """Lo mas importante del archivo.

    El diccionario es la lista mas sensible que tiene la empresa. Si desde el
    panel se pudiera reconstruir, Aegis seria el agujero que dice tapar.
    """

    def test_la_evidencia_lleva_la_etiqueta_y_no_el_termino(self):
        hallazgos = diccionario.buscar("El contrato con Bancolombia", TERMINOS)
        self.assertEqual(hallazgos[0].evidence, "<cliente>")
        self.assertNotIn("Bancolombia", hallazgos[0].evidence)

    def test_el_rule_id_tampoco_lleva_el_termino(self):
        hallazgos = diccionario.buscar("Hablemos del Proyecto Fenix", TERMINOS)
        self.assertNotIn("fenix", hallazgos[0].rule_id.lower())

    def test_ningun_termino_aparece_en_ningun_campo_del_hallazgo(self):
        hallazgos = diccionario.buscar(
            "Bancolombia y el Proyecto Fenix en intranet.acme.co", TERMINOS
        )
        self.assertTrue(hallazgos)
        for hallazgo in hallazgos:
            texto = f"{hallazgo.rule_id} {hallazgo.evidence}".lower()
            for termino in TERMINOS:
                with self.subTest(regla=hallazgo.rule_id, termino=termino):
                    self.assertNotIn(termino.lower(), texto)


class TestEscondidoNoSirve(unittest.TestCase):
    """Las mismas vistas que las reglas: si comprimir alcanzara, no serviria."""

    def test_en_texto_plano(self):
        hallazgos = scan_payload(_cuerpo("El Proyecto Fenix arranca"), "", TERMINOS).findings
        self.assertTrue(any(h.rule_id.startswith("empresa_") for h in hallazgos))

    def test_comprimido_con_gzip(self):
        cuerpo = gzip.compress(_cuerpo("El Proyecto Fenix arranca"))
        hallazgos = scan_payload(cuerpo, "", TERMINOS).findings
        self.assertTrue(any(h.rule_id.startswith("empresa_") for h in hallazgos))

    def test_pasado_por_base64(self):
        oculto = base64.b64encode("El Proyecto Fenix arranca".encode()).decode()
        hallazgos = scan_payload(_cuerpo(oculto), "", TERMINOS).findings
        self.assertTrue(any(h.rule_id.startswith("empresa_") for h in hallazgos))

    def test_sin_terminos_el_escaneo_no_cambia(self):
        # La lista es opcional: un agente sin diccionario protege igual con todo
        # lo demas.
        hallazgos = scan_payload(_cuerpo("El Proyecto Fenix arranca")).findings
        self.assertFalse(any(h.rule_id.startswith("empresa_") for h in hallazgos))


class TestLaDecisionYLaLeccion(unittest.TestCase):
    def test_por_defecto_corta(self):
        # Un termino declarado es una decision explicita de la empresa, no una
        # probabilidad: merece la misma autoridad que una regla de formato.
        hallazgos = diccionario.buscar("El Proyecto Fenix arranca", TERMINOS)
        self.assertEqual(
            decidir_sobre("ai_approved", hallazgos, Policy(company_terms=TERMINOS)),
            "block_content",
        )

    def test_la_empresa_puede_pedir_que_solo_avise(self):
        politica = Policy(company_terms=TERMINOS, company_terms_action="warn")
        hallazgos = diccionario.buscar("El Proyecto Fenix arranca", TERMINOS)
        self.assertEqual(decidir_sobre("ai_approved", hallazgos, politica), "warn")

    def test_hay_una_leccion_para_la_familia_entera(self):
        # Las etiquetas las inventa la empresa, asi que no se pueden escribir
        # todas a mano.
        for rule_id in ("empresa_cliente", "empresa_proyecto", "empresa_lo_que_sea"):
            with self.subTest(rule_id=rule_id):
                leccion = lesson_for(rule_id)
                self.assertIn("interna de la empresa", leccion["title"])

    def test_la_leccion_no_puede_nombrar_el_termino(self):
        leccion = lesson_for("empresa_cliente")
        texto = " ".join(leccion.values()).lower()
        for termino in TERMINOS:
            with self.subTest(termino=termino):
                self.assertNotIn(termino.lower(), texto)


class TestLaPoliticaLoTransporta(unittest.TestCase):
    def test_el_diccionario_va_y_vuelve_del_json(self):
        politica = Policy(company_terms=TERMINOS, company_terms_action="warn")
        self.assertEqual(Policy.desde_dict(politica.a_dict()), politica)

    def test_una_politica_parcial_no_borra_el_diccionario(self):
        # Es la lista que mas caro sale perder por accidente.
        con_lista = Policy(company_terms=TERMINOS)
        mezclada = Policy.desde_dict({"tenant_id": "otra"}, con_lista)
        self.assertEqual(mezclada.company_terms, TERMINOS)

    def test_la_lista_tiene_un_tope(self):
        muchos = {f"termino-numero-{i}": "x" for i in range(diccionario.MAX_TERMINOS + 50)}
        self.assertLessEqual(len(diccionario.utilizables(muchos)), diccionario.MAX_TERMINOS)


if __name__ == "__main__":
    unittest.main()
