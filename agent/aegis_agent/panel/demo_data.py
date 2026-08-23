from __future__ import annotations

import random

# Semana sintetica para que el panel se pueda mostrar sin haber generado trafico.
# Vive aca y no en los tests porque tambien la usa el panel desplegado: los datos
# de una demo publica tienen que ser inventados, nunca la navegacion de nadie.

AREAS = {
    "marketing": ["u_ana", "u_pablo"],
    "contabilidad": ["u_carmen"],
    "ingenieria": ["u_diego", "u_sofia"],
    "recursos humanos": ["u_lucia"],
}

DESTINOS = [
    ("claude.ai", "ai_approved"),
    ("chatgpt.com", "ai_unapproved"),
    ("gemini.google.com", "ai_unapproved"),
    ("otter.ai", "ai_unapproved"),
    ("gamma.app", "ai_unknown"),
]

DETECCIONES = [
    ("aws_access_key_id", "secret", "critical"),
    ("db_connection_string", "secret", "critical"),
    ("archivo_critico", "secret", "critical"),
    ("csv_pii_export", "internal_data", "critical"),
    ("bulk_pii_export", "internal_data", "critical"),
    ("sql_insert_rows", "internal_data", "high"),
    ("email_address", "pii", "medium"),
    ("confidentiality_marker", "internal_data", "medium"),
]

EVIDENCIAS = {
    "secret": "AKIA****",
    "internal_data": "<archivo:env>",
    "pii": "<email>",
}


def semana_simulada(seed: int = 7, cantidad: int = 120) -> list[dict]:
    rng = random.Random(seed)
    eventos = []
    for indice in range(cantidad):
        area = rng.choice(list(AREAS))
        user = rng.choice(AREAS[area])
        domain, classification = rng.choice(DESTINOS)
        rule, category, severity = rng.choice(DETECCIONES)
        action = "blocked" if severity == "critical" else rng.choice(["warned", "blocked"])
        eventos.append(
            {
                "event_id": f"demo-{indice}",
                "tenant_id": "acme",
                "actor": {"user_id": user, "area": area, "role": "employee"},
                "destination": {
                    "domain": domain,
                    "classification": classification,
                    "process": "browser",
                },
                "detection": {
                    "rule_id": rule,
                    "category": category,
                    "severity": severity,
                    "confidence": 0.95,
                    "engine": "t1_rules",
                    "evidence": EVIDENCIAS[category],
                },
                "action": action,
                "payload_stats": {"bytes": rng.randint(200, 90000), "truncated": False},
                "occurred_at": f"2026-08-{18 + indice % 5:02d}T{9 + indice % 9:02d}:12:00Z",
                "agent_version": "0.1.0",
            }
        )

    # Un caso deliberado de reincidencia: sin el, el panel no muestra el patron
    # que justifica toda la parte pedagogica del producto.
    eventos.extend(
        {
            "event_id": f"demo-r{i}",
            "tenant_id": "acme",
            "actor": {"user_id": "u_pablo", "area": "marketing", "role": "employee"},
            "destination": {
                "domain": "chatgpt.com",
                "classification": "ai_unapproved",
                "process": "browser",
            },
            "detection": {
                "rule_id": "aws_access_key_id",
                "category": "secret",
                "severity": "critical",
                "confidence": 0.99,
                "engine": "t1_rules",
                "evidence": "AKIA****",
            },
            "action": "blocked",
            "payload_stats": {"bytes": 900, "truncated": False},
            "occurred_at": f"2026-08-2{i}T11:00:00Z",
            "agent_version": "0.1.0",
        }
        for i in range(1, 5)
    )
    return eventos
