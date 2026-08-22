"""El almacen duradero, y la frontera que tiene que sostener al cruzarlo.

Conectar una base hospedada es el momento en que los eventos de Aegis dejan de
vivir en la maquina de la empresa y se van a un tercero. Todo lo que este
archivo prueba sale de ahi:

  1. **Que solo cruce lo nombrado.** El resto del sistema usa lista negra
     (`lleva_contenido` rechaza campos prohibidos), que sirve para rechazar. Para
     salir del equipo hace falta lo contrario: una lista blanca, para que un
     campo nuevo se quede afuera por omision en vez de filtrarse por descuido.
  2. **Que el panel no cambie.** La fila es plana y el contrato es anidado; si la
     vuelta no fuera exacta, las metricas mentirian sin que nada falle.
  3. **Que sin Supabase todo siga igual.** Es opcional a proposito: el agente
     protege sin backend y el panel se dibuja sin base.
  4. **Que un almacen caido degrade y no tumbe.** Que no conteste no puede
     dejar al panel vacio ni perder el evento que llego mientras tanto.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "web"))

from aegis_agent.panel.metrics import compute  # noqa: E402
from aegis_backend import supabase  # noqa: E402

EVENTO = {
    "event_id": "abc123",
    "tenant_id": "acme",
    "actor": {"user_id": "u_ana", "area": "marketing", "role": "employee"},
    "destination": {
        "domain": "chatgpt.com",
        "classification": "ai_unapproved",
        "process": "browser",
    },
    "detection": {
        "rule_id": "aws_access_key_id",
        "category": "secret",
        "severity": "critical",
        "confidence": 1.0,
        "engine": "t1_rules",
        "evidence": "AKIA****",
    },
    "action": "blocked",
    "payload_stats": {"bytes": 412, "truncated": False},
    "occurred_at": "2026-08-22T10:00:00Z",
    "agent_version": "0.1.0",
}


class TestSoloCruzaLoNombrado(unittest.TestCase):
    """Lo mas importante del archivo: la lista blanca del borde."""

    def test_un_campo_con_contenido_no_llega_a_la_fila(self):
        # El servicio ya rechaza estos eventos antes de guardarlos. Esto es la
        # segunda cerradura: si la primera fallara, aca tampoco sale.
        sucio = {**EVENTO, "prompt": "la contrasena es hunter2", "raw": b"x"}
        fila = supabase._a_fila(sucio)
        self.assertNotIn("prompt", fila)
        self.assertNotIn("raw", fila)

    def test_un_campo_nuevo_se_queda_afuera_por_omision(self):
        # La razon de ser de la lista blanca: nadie tiene que acordarse de venir
        # a prohibir el campo que agrego el mes que viene.
        fila = supabase._a_fila({**EVENTO, "transcripcion_completa": "..."})
        self.assertNotIn("transcripcion_completa", fila)

    def test_ningun_valor_del_evento_sucio_aparece_en_la_fila(self):
        secreto = "AKIAIOSFODNN7EXAMPLE y la clave es hunter2"
        fila = supabase._a_fila({**EVENTO, "content": secreto, "body": secreto})
        self.assertNotIn(secreto, " ".join(str(v) for v in fila.values()))

    def test_la_evidencia_se_recorta(self):
        # Es la unica columna donde un bug de otro lado podria colar texto real:
        # las demas son enumeraciones, dominios y numeros.
        largo = {**EVENTO, "detection": {**EVENTO["detection"], "evidence": "x" * 500}}
        self.assertEqual(len(supabase._a_fila(largo)["evidencia"]), 32)

    def test_la_tabla_no_tiene_columna_para_contenido(self):
        columnas = set(supabase._a_fila(EVENTO))
        for prohibida in ("payload", "content", "text", "prompt", "body", "raw"):
            with self.subTest(columna=prohibida):
                self.assertNotIn(prohibida, columnas)


class TestElPanelNoSeEntera(unittest.TestCase):
    def test_la_vuelta_conserva_el_contrato(self):
        self.assertEqual(supabase._a_evento(supabase._a_fila(EVENTO)), EVENTO)

    def test_las_metricas_dan_lo_mismo_por_los_dos_caminos(self):
        directo = compute([EVENTO])
        pasando = compute([supabase._a_evento(supabase._a_fila(EVENTO))])
        self.assertEqual(directo.blocked, pasando.blocked)
        self.assertEqual(directo.by_rule, pasando.by_rule)
        self.assertEqual(directo.by_destination, pasando.by_destination)

    def test_la_fecha_que_devuelve_postgres_cae_en_la_misma_hora(self):
        """El agente manda "...T10:00:00Z" y Postgres devuelve "...T10:00:00+00:00".

        El timeline agrupa por `occurred_at[:13]`, asi que los dos tienen que
        caer en el mismo casillero. Si no, la grafica por hora se parte en dos
        el dia que los eventos empiecen a venir de la base en vez del disco, y
        no falla nada: solo muestra mal.
        """

        del_agente = compute([EVENTO]).timeline
        de_postgres = compute(
            [{**EVENTO, "occurred_at": "2026-08-22T10:00:00+00:00"}]
        ).timeline
        self.assertEqual(del_agente, de_postgres)

    def test_un_evento_sin_deteccion_no_inventa_una(self):
        # Un envio permitido no tiene hallazgo, y una deteccion vacia en vez de
        # None haria que el panel contara reglas que nunca dispararon.
        limpio = {**EVENTO, "detection": None, "action": "allowed"}
        self.assertIsNone(supabase._a_evento(supabase._a_fila(limpio))["detection"])


class TestSinSupabaseTodoSigueIgual(unittest.TestCase):
    def setUp(self):
        parche = patch.dict(os.environ, {}, clear=False)
        parche.start()
        self.addCleanup(parche.stop)
        for nombre in (
            "SUPABASE_URL",
            "SUPABASE_SERVICE_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_KEY",
        ):
            os.environ.pop(nombre, None)

        # Y tambien el archivo de secretos del HOME: sin esto, la suite empieza
        # a pasar o a fallar segun si quien la corre tiene Supabase configurado
        # en su maquina. Es el mismo acoplamiento que costo veintitres tests
        # rojos en su momento (ver tests/aislamiento.py).
        from aegis_backend import secretos

        sin_archivo = patch.object(
            secretos, "ARCHIVO_POR_DEFECTO", Path("no-existe") / "secretos.env"
        )
        sin_archivo.start()
        self.addCleanup(sin_archivo.stop)

    def test_no_esta_configurado(self):
        self.assertFalse(supabase.configurado())

    def test_guardar_no_falla_ni_miente(self):
        self.assertFalse(supabase.guardar_evento(EVENTO))

    def test_leer_devuelve_none_y_no_una_lista_vacia(self):
        # La diferencia importa: [] seria "no hay eventos" y apagaria el panel;
        # None es "no se pudo saber" y hace que se caiga al nivel de abajo.
        self.assertIsNone(supabase.leer_eventos())

    def test_las_variables_se_leen_en_cada_llamada(self):
        # Si se resolvieran al importar, configurar Supabase pediria reiniciar.
        os.environ["SUPABASE_URL"] = "https://x.supabase.co"
        os.environ["SUPABASE_SERVICE_KEY"] = "clave"
        self.assertTrue(supabase.configurado())


class TestUnAlmacenCaidoDegrada(unittest.TestCase):
    """Que Supabase no conteste no puede costar ni el panel ni un evento."""

    def setUp(self):
        import app as servicio

        self.servicio = servicio
        servicio._memoria.clear()
        servicio._cache = None
        self.addCleanup(servicio._memoria.clear)

    def test_si_no_contesta_se_cae_al_nivel_de_abajo(self):
        self.servicio._memoria.insert(0, EVENTO)
        with patch.object(self.servicio.supabase, "configurado", return_value=True):
            with patch.object(self.servicio.supabase, "leer_eventos", return_value=None):
                self.assertEqual(self.servicio.eventos(), [EVENTO])

    def test_un_evento_que_no_se_pudo_subir_no_se_pierde(self):
        with patch.object(self.servicio.supabase, "configurado", return_value=True):
            with patch.object(self.servicio.supabase, "guardar_evento", return_value=False):
                self.servicio.guardar(EVENTO)
        self.assertIn(EVENTO, self.servicio._memoria)

    def test_lo_que_sube_bien_no_se_guarda_dos_veces(self):
        with patch.object(self.servicio.supabase, "configurado", return_value=True):
            with patch.object(self.servicio.supabase, "guardar_evento", return_value=True):
                self.servicio.guardar(EVENTO)
        self.assertEqual(self.servicio._memoria, [])

    def test_una_base_vacia_no_se_confunde_con_una_caida(self):
        # Recien conectada, la base contesta []. El panel muestra la semana
        # simulada, que es lo mismo que hacia antes; lo que no puede pasar es
        # que se quede pegado ahi cuando entre el primer evento de verdad.
        with patch.object(self.servicio.supabase, "configurado", return_value=True):
            with patch.object(self.servicio.supabase, "leer_eventos", return_value=[]):
                self.assertTrue(self.servicio.eventos())
            with patch.object(self.servicio.supabase, "leer_eventos", return_value=[EVENTO]):
                self.servicio._cache = None
                self.assertEqual(self.servicio.eventos(), [EVENTO])

    def test_el_almacen_se_nombra_por_lo_que_esta_corriendo(self):
        with patch.object(self.servicio.supabase, "configurado", return_value=True):
            self.assertEqual(self.servicio.almacen(), "supabase")
        with patch.object(self.servicio.supabase, "configurado", return_value=False):
            self.assertIn(self.servicio.almacen(), ("kv", "disco", "memoria"))


class TestNoSeConsultaPorCadaArchivo(unittest.TestCase):
    """Servir el front no puede costar una consulta a la base.

    `do_GET` leia los eventos arriba de todo, antes de mirar la ruta. Con el
    almacen en memoria era gratis; contra una base hospedada, cada .js, cada
    fuente y cada icono del panel se volvia una llamada de red para armar una
    respuesta que ni los mira.
    """

    def test_un_archivo_del_front_no_toca_el_almacen(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        import socket

        import app as servicio

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            puerto = s.getsockname()[1]

        servidor = ThreadingHTTPServer(("127.0.0.1", puerto), servicio.Handler)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)

        with patch.object(servicio, "eventos", wraps=servicio.eventos) as espia:
            conexion = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
            self.addCleanup(conexion.close)
            conexion.request("GET", "/main.js")
            conexion.getresponse().read()

        self.assertEqual(espia.call_count, 0)


if __name__ == "__main__":
    unittest.main()
