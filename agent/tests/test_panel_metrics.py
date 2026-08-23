"""El panel se calcula sobre eventos redactados, y eso no es un detalle.

El test que importa mas de todos es el ultimo: que ninguna metrica pueda exponer
contenido, porque el contenido nunca llego al evento.
"""

import json
import unittest

from aegis_agent.panel.metrics import (
    REPEAT_THRESHOLD,
    compute,
    filter_by_range,
    repeat_offenders,
)


def evento(
    *,
    user="u_ana",
    area="marketing",
    domain="claude.ai",
    classification="ai_approved",
    rule="aws_access_key_id",
    category="secret",
    severity="critical",
    action="blocked",
    hora="2026-08-22T14",
    proceso="browser",
):
    detection = None
    if rule:
        detection = {
            "rule_id": rule,
            "category": category,
            "severity": severity,
            "confidence": 0.99,
            "engine": "t1_rules",
            "evidence": "AKIA****",
        }
    return {
        "event_id": f"{user}{hora}{rule}{action}",
        "tenant_id": "acme",
        "actor": {"user_id": user, "area": area, "role": "employee"},
        "destination": {
            "domain": domain,
            "classification": classification,
            "process": proceso,
        },
        "detection": detection,
        "action": action,
        "payload_stats": {"bytes": 100, "truncated": False},
        "occurred_at": f"{hora}:03:11Z",
        "agent_version": "0.1.0",
    }


class TestResumen(unittest.TestCase):
    def test_cuenta_acciones(self):
        metrics = compute(
            [
                evento(action="blocked"),
                evento(action="blocked"),
                evento(action="warned", severity="medium"),
                evento(action="allowed", rule=None),
            ]
        )
        self.assertEqual(metrics.total, 4)
        self.assertEqual(metrics.blocked, 2)
        self.assertEqual(metrics.warned, 1)
        self.assertEqual(metrics.allowed, 1)
        self.assertEqual(round(metrics.block_rate), 50)

    def test_sin_eventos_no_divide_por_cero(self):
        metrics = compute([])
        self.assertEqual(metrics.total, 0)
        self.assertEqual(metrics.block_rate, 0.0)


class TestAgregados(unittest.TestCase):
    def test_destinos_ordenados_por_frecuencia(self):
        metrics = compute(
            [evento(domain="claude.ai")] * 3 + [evento(domain="chatgpt.com", classification="ai_unapproved")]
        )
        self.assertEqual(metrics.by_destination[0][0], "claude.ai")
        self.assertEqual(metrics.by_destination[0][2], 3)

    def test_shadow_ai_separa_lo_catalogado_de_lo_descubierto(self):
        metrics = compute(
            [
                evento(domain="chatgpt.com", classification="ai_unapproved"),
                evento(domain="asistente-raro.co", classification="ai_unknown"),
            ]
        )
        self.assertEqual(metrics.shadow_domains, ["chatgpt.com"])
        self.assertEqual(metrics.uncatalogued_domains, ["asistente-raro.co"])

    def test_la_herramienta_se_cuenta_aparte_del_destino(self):
        """`by_destination` dice adonde fue; `by_process` dice con que.

        Son preguntas distintas y las dos deciden politica: una persona pegando
        un fragmento en chatgpt.com no es un agente de codigo mandando un
        repositorio entero al mismo dominio.
        """

        metrics = compute(
            [
                evento(proceso="claude-code"),
                evento(proceso="claude-code", hora="2026-08-22T15"),
                evento(proceso="browser", hora="2026-08-22T16"),
            ]
        )
        self.assertEqual(metrics.by_process, [("claude-code", 2), ("browser", 1)])

    def test_lo_que_no_se_pudo_atribuir_se_cuenta_igual(self):
        # "desconocido" es un valor legitimo del contrato: no siempre se puede
        # atribuir la conexion a un proceso. Esconderlo daria un ranking que no
        # suma al total y el panel mentiria por omision.
        metrics = compute([evento(proceso=""), evento(proceso="cursor", hora="2026-08-22T15")])
        self.assertEqual(dict(metrics.by_process), {"desconocido": 1, "cursor": 1})
        self.assertEqual(sum(v for _, v in metrics.by_process), metrics.total)

    def test_riesgo_por_area_cuenta_los_criticos(self):
        metrics = compute(
            [
                evento(area="marketing", severity="critical"),
                evento(area="marketing", severity="medium"),
                evento(area="contabilidad", severity="medium"),
            ]
        )
        por_area = {area: (total, criticos) for area, total, criticos in metrics.by_area}
        self.assertEqual(por_area["marketing"], (2, 1))
        self.assertEqual(por_area["contabilidad"], (1, 0))

    def test_las_personas_se_ordenan_por_criticos(self):
        metrics = compute(
            [evento(user="u_ana", severity="medium")] * 5
            + [evento(user="u_juan", severity="critical")]
        )
        self.assertEqual(metrics.people_at_risk[0][0], "u_juan")

    def test_linea_de_tiempo_agrupa_por_hora(self):
        metrics = compute(
            [evento(hora="2026-08-22T14"), evento(hora="2026-08-22T14"), evento(hora="2026-08-22T15")]
        )
        self.assertEqual(metrics.timeline, [("2026-08-22T14", 2), ("2026-08-22T15", 1)])


class TestReincidencia(unittest.TestCase):
    def test_repetir_el_mismo_error_se_detecta(self):
        eventos = [evento(user="u_ana", rule="aws_access_key_id")] * REPEAT_THRESHOLD
        self.assertEqual(repeat_offenders(eventos), {"u_ana": ["aws_access_key_id"]})

    def test_un_descuido_aislado_no_es_un_patron(self):
        eventos = [evento(user="u_ana", rule="aws_access_key_id")] * (REPEAT_THRESHOLD - 1)
        self.assertEqual(repeat_offenders(eventos), {})

    def test_errores_distintos_no_se_suman_entre_si(self):
        eventos = [
            evento(user="u_ana", rule="aws_access_key_id"),
            evento(user="u_ana", rule="email_address"),
            evento(user="u_ana", rule="jwt"),
        ]
        self.assertEqual(repeat_offenders(eventos), {})


class TestFiltroDeRango(unittest.TestCase):
    def test_sin_limites_devuelve_todo(self):
        eventos = [evento(hora="2026-08-18T09"), evento(hora="2026-08-22T14")]
        self.assertEqual(filter_by_range(eventos), eventos)

    def test_desde_deja_afuera_lo_anterior(self):
        viejo = evento(hora="2026-08-18T09")
        nuevo = evento(hora="2026-08-22T14")
        resultado = filter_by_range([viejo, nuevo], since="2026-08-20T00:00:00Z")
        self.assertEqual(resultado, [nuevo])

    def test_hasta_deja_afuera_lo_posterior(self):
        viejo = evento(hora="2026-08-18T09")
        nuevo = evento(hora="2026-08-22T14")
        resultado = filter_by_range([viejo, nuevo], until="2026-08-20T00:00:00Z")
        self.assertEqual(resultado, [viejo])

    def test_desde_y_hasta_juntos_acotan_los_dos_lados(self):
        antes = evento(hora="2026-08-15T09")
        adentro = evento(hora="2026-08-19T09")
        despues = evento(hora="2026-08-25T09")
        resultado = filter_by_range(
            [antes, adentro, despues],
            since="2026-08-18T00:00:00Z",
            until="2026-08-20T00:00:00Z",
        )
        self.assertEqual(resultado, [adentro])

    def test_el_limite_es_inclusivo(self):
        # Quien elige "desde el lunes" espera ver el evento del lunes mismo.
        limite = evento(hora="2026-08-20T00")
        resultado = filter_by_range([limite], since="2026-08-20T00:00:00Z")
        self.assertEqual(resultado, [limite])

    def test_un_evento_sin_fecha_no_pasa_un_filtro_con_desde(self):
        sin_fecha = evento()
        sin_fecha["occurred_at"] = ""
        resultado = filter_by_range([sin_fecha], since="2026-08-01T00:00:00Z")
        self.assertEqual(resultado, [])


class TestPrivacidad(unittest.TestCase):
    def test_ninguna_metrica_puede_exponer_contenido(self):
        # El panel solo ve lo que el agente subio, y el agente nunca sube texto.
        eventos = [evento(), evento(domain="chatgpt.com", classification="ai_unapproved")]
        serializado = json.dumps(
            {
                "destinos": compute(eventos).by_destination,
                "reglas": compute(eventos).by_rule,
                "personas": compute(eventos).people_at_risk,
            },
            ensure_ascii=False,
        )
        for filtrado in ("AKIAIOSFODNN7EXAMPLE", "postgres://", "@acme.co"):
            self.assertNotIn(filtrado, serializado)


if __name__ == "__main__":
    unittest.main()
