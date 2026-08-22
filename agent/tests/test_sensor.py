"""Capa D: las aplicaciones que hablan con una IA sin pasar por Aegis.

Lo que separa una conexion cubierta de una que no lo esta no es una heuristica:
la que usa el proxy va a 127.0.0.1 y la que lo esquiva va a la IP remota.
"""

import unittest

from aegis_agent.sensor import PuntoCiego, SensorDePuntosCiegos


class Remoto:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


class Conexion:
    def __init__(self, pid, ip, port):
        self.pid = pid
        self.raddr = Remoto(ip, port)


CATALOGO = {"chat.openai.com", "api.anthropic.com"}
DNS = {
    "104.18.0.1": "chat.openai.com",
    "160.79.104.10": "api.anthropic.com",
    "142.250.1.1": "www.google.com",
    "20.1.1.1": "",
}

PID_DEL_PROXY = 4242


def sensor(conexiones):
    return SensorDePuntosCiegos(
        pid_del_proxy=PID_DEL_PROXY,
        es_ia=lambda host: host in CATALOGO,
        resolver=lambda ip: DNS.get(ip, ""),
        conexiones=lambda: conexiones,
    )


class TestDeteccion(unittest.TestCase):
    def test_una_app_que_esquiva_el_proxy_se_ve(self):
        hallazgos = sensor([Conexion(900, "104.18.0.1", 443)]).revisar()
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].host, "chat.openai.com")
        self.assertIsInstance(hallazgos[0], PuntoCiego)

    def test_lo_que_pasa_por_el_proxy_no_es_un_punto_ciego(self):
        """El propio proxy habla con la IA: esa conexion es Aegis funcionando."""

        hallazgos = sensor([Conexion(PID_DEL_PROXY, "104.18.0.1", 443)]).revisar()
        self.assertEqual(hallazgos, [])

    def test_una_app_conectada_al_proxy_local_no_cuenta(self):
        """Ir a 127.0.0.1 es, por definicion, estar pasando por Aegis."""

        hallazgos = sensor([Conexion(900, "127.0.0.1", 8899)]).revisar()
        self.assertEqual(hallazgos, [])

    def test_el_trafico_que_no_va_a_una_ia_no_se_reporta(self):
        """Todo el mundo habla con servidores todo el dia; solo importan las IA.

        Sin este filtro el panel se llenaria de Windows Update y del antivirus, y
        el punto ciego de verdad quedaria enterrado entre ruido.
        """

        hallazgos = sensor([Conexion(900, "142.250.1.1", 443)]).revisar()
        self.assertEqual(hallazgos, [])

    def test_una_ip_que_no_resuelve_no_se_inventa(self):
        hallazgos = sensor([Conexion(900, "20.1.1.1", 443)]).revisar()
        self.assertEqual(hallazgos, [])

    def test_otros_puertos_no_interesan(self):
        hallazgos = sensor([Conexion(900, "104.18.0.1", 22)]).revisar()
        self.assertEqual(hallazgos, [])


class TestRuido(unittest.TestCase):
    def test_el_mismo_punto_ciego_se_reporta_una_sola_vez(self):
        """Una pestana abierta sostiene conexiones por minutos.

        Sin esto el panel recibiria el mismo hallazgo cada diez segundos y la
        empresa no podria leer nada.
        """

        s = sensor([Conexion(900, "104.18.0.1", 443)])
        self.assertEqual(len(s.revisar()), 1)
        self.assertEqual(s.revisar(), [])

    def test_dos_procesos_distintos_son_dos_hallazgos(self):
        s = sensor(
            [Conexion(900, "104.18.0.1", 443), Conexion(901, "104.18.0.1", 443)]
        )
        self.assertEqual(len(s.revisar()), 2)


class TestResolucion(unittest.TestCase):
    def test_lo_que_el_proxy_ya_sabe_le_gana_al_dns_inverso(self):
        """Las IPs de un CDN casi nunca resuelven al nombre del servicio.

        El proxy si sabe a que host iba cada conexion que paso por el, y ese dato
        vale mas que cualquier gethostbyaddr.
        """

        s = sensor([Conexion(900, "1.2.3.4", 443)])
        self.assertEqual(s.revisar(), [])
        s.aprender("1.2.3.4", "api.anthropic.com")
        hallazgos = s.revisar()
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].host, "api.anthropic.com")

    def test_la_ip_se_resuelve_una_sola_vez(self):
        llamadas = []

        def resolver(ip):
            llamadas.append(ip)
            return DNS.get(ip, "")

        s = SensorDePuntosCiegos(
            pid_del_proxy=PID_DEL_PROXY,
            es_ia=lambda host: host in CATALOGO,
            resolver=resolver,
            conexiones=lambda: [Conexion(900, "142.250.1.1", 443)],
        )
        s.revisar()
        s.revisar()
        self.assertEqual(llamadas, ["142.250.1.1"])


class TestCatalogoHaciaAdelante(unittest.TestCase):
    """Preguntar "que IPs tiene chat.openai.com" en vez de "de quien es esta IP".

    Medido contra la tabla real de una maquina: el DNS inverso tardo 28 segundos
    en 23 conexiones y no identifico ninguna, porque las IPs de un CDN no tienen
    registro inverso propio. Resolviendo el catalogo hacia adelante, la misma
    pasada tarda 14 ms y encuentra los puntos ciegos que si habia.
    """

    def _sensor_con_catalogo(self, conexiones):
        s = SensorDePuntosCiegos(
            pid_del_proxy=PID_DEL_PROXY,
            es_ia=lambda host: host in CATALOGO,
            conexiones=lambda: conexiones,
        )
        s.cargar_catalogo(
            ["chat.openai.com"],
            resolver_hacia_adelante=lambda d: ["203.0.113.7", "203.0.113.8"],
        )
        return s

    def test_una_ip_del_catalogo_se_reconoce(self):
        hallazgos = self._sensor_con_catalogo(
            [Conexion(900, "203.0.113.7", 443)]
        ).revisar()
        self.assertEqual(len(hallazgos), 1)
        self.assertEqual(hallazgos[0].host, "chat.openai.com")

    def test_revisar_no_consulta_la_red(self):
        """Si revisar() resolviera, una pasada tardaria segundos en vez de milisegundos."""

        s = SensorDePuntosCiegos(
            pid_del_proxy=PID_DEL_PROXY,
            es_ia=lambda host: host in CATALOGO,
            conexiones=lambda: [Conexion(900, "198.51.100.1", 443)],
        )
        self.assertIsNone(s.resolver)
        self.assertEqual(s.revisar(), [])

    def test_un_dominio_que_no_resuelve_no_rompe_la_carga(self):
        s = SensorDePuntosCiegos(
            pid_del_proxy=PID_DEL_PROXY,
            es_ia=lambda host: host in CATALOGO,
            conexiones=lambda: [],
        )
        aprendidas = s.cargar_catalogo(
            ["no-existe.invalid", "chat.openai.com"],
            resolver_hacia_adelante=lambda d: [] if "invalid" in d else ["203.0.113.7"],
        )
        self.assertEqual(aprendidas, 1)


class TestSinPsutil(unittest.TestCase):
    def test_sin_conexiones_no_se_cae(self):
        self.assertEqual(sensor([]).revisar(), [])


if __name__ == "__main__":
    unittest.main()
