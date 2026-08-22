"""Que aplicacion abrio la conexion, y que puede hacer Aegis con ella.

Hasta aca todos los eventos decian `process: "browser"`, incluso cuando el envio
venia de un CLI. El contrato de datos pide ese campo desde el primer dia y
estaba mintiendo, asi que el panel no podia distinguir a una persona pegando un
fragmento de un agente mandando un repositorio entero.

Lo que se prueba aca son dos cosas distintas y hay que no confundirlas:

  - La ATRIBUCION: que el evento diga la verdad. Es visibilidad.
  - La POLITICA POR APLICACION: que una app nombrada pueda quedar en modo
    observacion. Es enforcement, y tiene una regla que no se negocia, porque es
    lo que separa esto de romper el ADR 0002: **nombrar una app solo puede
    aflojarla**. Lo desconocido se queda con lo estricto, siempre.

El detector sigue sin enterarse de nada de esto: recibe texto y un destino, que
es lo que hace que el mismo codigo cubra un navegador, un IDE y una app que
todavia no existe.
"""

import unittest

from aegis_agent import procesos
from aegis_agent.detect.types import Finding
from aegis_agent.policy import BLOQUEAR, OBSERVAR, Policy, decidir_sobre, modo_de_la_app


def _hallazgo(rule_id="aws_access_key_id", category="secret", severity="critical"):
    return Finding(
        rule_id=rule_id,
        category=category,
        severity=severity,
        confidence=0.99,
        evidence="AKIA****",
        start=0,
        end=1,
    )


class TestLoDesconocidoSigueSiendoEstricto(unittest.TestCase):
    """La regla que sostiene que esto no reduzca la cobertura (ADR 0002)."""

    def test_una_app_que_nadie_nombro_se_queda_con_lo_estricto(self):
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertEqual(modo_de_la_app("herramienta-rara.exe", politica), BLOQUEAR)

    def test_sin_atribucion_tampoco_se_afloja(self):
        # Si la tabla de conexiones no dijo nada, la respuesta no puede ser
        # "entonces dejalo pasar".
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        for proceso in ("", procesos.DESCONOCIDO):
            with self.subTest(proceso=proceso):
                self.assertEqual(modo_de_la_app(proceso, politica), BLOQUEAR)

    def test_sin_reglas_por_app_todo_sigue_como_antes(self):
        self.assertEqual(modo_de_la_app("chrome.exe", Policy()), BLOQUEAR)

    def test_una_app_nombrada_no_puede_endurecerse_mas_alla_de_lo_estricto(self):
        # Solo hay dos modos y el estricto ya es el techo: nombrar una app nunca
        # puede convertir un aviso en un bloqueo.
        politica = Policy(app_actions={"chrome.exe": BLOQUEAR})
        solo_pii = _hallazgo("email_address", "pii", "medium")
        self.assertEqual(
            decidir_sobre("ai_approved", [solo_pii], politica, "chrome.exe"), "warn"
        )


class TestLaPoliticaPorAplicacion(unittest.TestCase):
    def test_una_app_en_observacion_avisa_en_vez_de_cortar(self):
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertEqual(
            decidir_sobre("ai_approved", [_hallazgo()], politica, "claude-code"), "warn"
        )

    def test_la_misma_fuga_desde_el_navegador_si_corta(self):
        # El contrapeso: si observar valiera para todos, no habria producto.
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertEqual(
            decidir_sobre("ai_approved", [_hallazgo()], politica, "chrome.exe"),
            "block_content",
        )

    def test_el_nombre_no_distingue_mayusculas(self):
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertEqual(modo_de_la_app("Claude-Code", politica), OBSERVAR)

    def test_observar_no_apaga_el_registro(self):
        # Lo que se pierde es el corte, no la visibilidad: "warn" tambien se
        # registra y llega al panel. Un modo observacion que ademas dejara de
        # ver seria un modo apagado.
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertNotEqual(
            decidir_sobre("ai_approved", [_hallazgo()], politica, "claude-code"),
            "allow",
        )

    def test_la_politica_por_app_viaja_en_el_json(self):
        politica = Policy(app_actions={"claude-code": OBSERVAR})
        self.assertEqual(Policy.desde_dict(politica.a_dict()), politica)


class TestLaMezclaNoResetea(unittest.TestCase):
    """Una politica parcial no puede cambiar lo que no nombro.

    Paso en vivo: un backend con codigo anterior devolvio una politica sin los
    campos nuevos y le devolvio el bloqueo a un equipo que estaba en modo
    observacion. En un producto de seguridad, el enforcement no puede cambiar
    porque alguien omitio una clave.
    """

    def test_un_campo_ausente_conserva_lo_que_habia(self):
        observacion = Policy(
            block_categories=frozenset(),
            warn_categories=frozenset({"secret", "internal_data", "pii"}),
        )
        mezclada = Policy.desde_dict({"unapproved_ai_action": "block_destination"}, observacion)
        self.assertEqual(mezclada.block_categories, frozenset())
        self.assertEqual(mezclada.unapproved_ai_action, "block_destination")

    def test_sin_base_se_cae_a_los_defaults_como_siempre(self):
        # El comportamiento viejo sigue disponible y es el correcto cuando de
        # verdad se quiere reconstruir una politica desde cero.
        self.assertEqual(Policy.desde_dict({}), Policy())

    def test_las_reglas_por_app_tambien_se_conservan(self):
        con_apps = Policy(app_actions={"claude-code": OBSERVAR})
        mezclada = Policy.desde_dict({"tenant_id": "otra"}, con_apps)
        self.assertEqual(mezclada.app_actions, {"claude-code": OBSERVAR})


class TestAtribucionDeProcesos(unittest.TestCase):
    """La resolucion en si. Sin psutil o sin permisos, "desconocido" es valido."""

    def setUp(self):
        procesos.olvidar()
        self.addCleanup(procesos.olvidar)

    def test_un_puerto_que_nadie_tiene_abierto_da_desconocido(self):
        proceso = procesos.del_puerto(1)
        self.assertEqual(proceso.nombre, procesos.DESCONOCIDO)
        self.assertFalse(proceso.conocido)

    def test_se_resuelve_el_proceso_de_una_conexion_propia(self):
        # Contra el sistema de verdad: se abre un socket y Aegis tiene que poder
        # decir que proceso lo abrio, porque ese es exactamente el mecanismo.
        import socket

        servidor = socket.socket()
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        cliente = socket.create_connection(servidor.getsockname(), timeout=5)
        self.addCleanup(servidor.close)
        self.addCleanup(cliente.close)

        proceso = procesos.del_puerto(cliente.getsockname()[1])

        if proceso.conocido:
            self.assertIn("python", proceso.nombre.lower())
            self.assertGreater(proceso.pid, 0)
        else:
            # Sin psutil o sin permisos para enumerar: es un resultado valido y
            # el producto tiene que seguir funcionando igual.
            self.assertEqual(proceso.nombre, procesos.DESCONOCIDO)

    def test_el_resultado_se_cachea_por_pid(self):
        import socket

        servidor = socket.socket()
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        cliente = socket.create_connection(servidor.getsockname(), timeout=5)
        self.addCleanup(servidor.close)
        self.addCleanup(cliente.close)

        puerto = cliente.getsockname()[1]
        primero = procesos.del_puerto(puerto)
        segundo = procesos.del_puerto(puerto)
        self.assertIs(primero, segundo)


class TestElNombreCanonico(unittest.TestCase):
    """La misma herramienta se instala distinto en cada maquina.

    Claude Code es `claude.exe` en un equipo y `node.exe ...cli.js` en otro. Una
    politica que dijera "claude.exe" solo serviria en el primero, asi que el
    nombre se normaliza y la politica de la empresa queda portable.
    """

    def test_el_ejecutable_ya_nombra_la_herramienta(self):
        self.assertEqual(procesos.normalizar("claude.exe"), "claude-code")
        self.assertEqual(procesos.normalizar("codex.exe"), "codex")

    def test_no_distingue_mayusculas(self):
        self.assertEqual(procesos.normalizar("ChatGPT.exe"), "chatgpt-app")

    def test_un_interprete_se_desambigua_con_la_linea_de_comandos(self):
        self.assertEqual(
            procesos.normalizar("node.exe", "node C:/Users/x/.claude/cli.js"),
            "claude-code",
        )

    def test_un_interprete_que_no_es_ninguna_herramienta_queda_como_esta(self):
        # Y esto importa: si un node.exe cualquiera se llamara "claude-code",
        # heredaria el modo observacion de una herramienta que no es.
        self.assertEqual(procesos.normalizar("node.exe", "node build.js"), "node.exe")

    def test_un_ejecutable_desconocido_no_se_inventa_un_nombre(self):
        self.assertEqual(procesos.normalizar("chrome.exe"), "chrome.exe")
        self.assertEqual(procesos.normalizar("exfiltrar.exe"), "exfiltrar.exe")

    def test_la_linea_de_comandos_no_alcanza_para_un_ejecutable_propio(self):
        # Un binario cualquiera no se convierte en Claude Code por mencionarlo:
        # la linea de comandos solo se mira cuando el ejecutable es un interprete.
        self.assertEqual(
            procesos.normalizar("exfiltrar.exe", "exfiltrar.exe --parecerse-a-claude"),
            "exfiltrar.exe",
        )


if __name__ == "__main__":
    unittest.main()
