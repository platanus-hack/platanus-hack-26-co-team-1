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
