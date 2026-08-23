from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from .detect.types import Finding

# El evento se escribe primero en disco y recien despues se sube. Si el backend
# esta caido el agente igual protege (ADR 0003) y la cola se drena cuando vuelva.
DEFAULT_QUEUE = Path(os.environ.get("AEGIS_QUEUE", "aegis-events.jsonl"))

# Subir al panel remoto es opcional y siempre en segundo plano.
UPLOAD_TIMEOUT = 6

_lock = threading.Lock()


def build_event(
    *,
    tenant_id: str,
    user_id: str,
    area: str,
    host: str,
    classification: str,
    process: str,
    finding: Finding | None,
    action: str,
    payload_bytes: int,
    truncated: bool,
) -> dict:
    """Arma el evento del contrato de datos.

    Todo lo que entra aca ya viene redactado o es metadato. El texto original no
    llega a esta funcion a proposito: no se puede filtrar lo que no se recibe.
    """

    detection = None
    if finding is not None:
        detection = {
            "rule_id": finding.rule_id,
            "category": finding.category,
            "severity": finding.severity,
            "confidence": finding.confidence,
            "engine": "t1_rules",
            "evidence": finding.evidence,
        }

    return {
        "event_id": uuid.uuid4().hex,
        "tenant_id": tenant_id,
        "actor": {"user_id": user_id, "area": area, "role": "employee"},
        "destination": {
            "domain": host,
            "classification": classification,
            "process": process,
        },
        "detection": detection,
        "action": action,
        "payload_stats": {"bytes": payload_bytes, "truncated": truncated},
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent_version": "0.1.0",
    }


def enqueue(event: dict, queue: Path = DEFAULT_QUEUE) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with _lock:
        with open(queue, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    _subir(line)


def _subir(line: str) -> None:
    """Manda el evento al panel remoto sin esperar la respuesta.

    Primero se escribe en disco y despues se intenta subir: si el envio falla, el
    evento no se pierde y la decision de bloquear ya se tomo hace rato. La red
    nunca esta en el camino de la proteccion.
    """

    destino = os.environ.get("AEGIS_EVENTS_URL")
    if destino:
        threading.Thread(target=_enviar, args=(destino, line), daemon=True).start()


def _enviar(destino: str, line: str) -> None:
    import urllib.error
    import urllib.request

    # El token de equipo dice a que empresa pertenece este agente. Sin el, el
    # panel contesta 401 y no guarda nada: hasta que existio el enrolamiento,
    # /v1/events aceptaba cualquier cosa de cualquiera.
    cabeceras = {"Content-Type": "application/json"}
    token = os.environ.get("AEGIS_EVENTS_TOKEN", "").strip()
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"

    peticion = urllib.request.Request(
        destino, data=line.encode("utf-8"), headers=cabeceras
    )
    try:
        urllib.request.urlopen(peticion, timeout=UPLOAD_TIMEOUT).close()
    except (urllib.error.URLError, OSError, ValueError):
        # El panel remoto es telemetria, no proteccion: que se caiga no cambia
        # nada de lo que ya paso en el equipo.
        pass
