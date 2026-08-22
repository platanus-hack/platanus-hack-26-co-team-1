from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

# Lo unico compartido entre todos los clientes es el veredicto de un dominio.
# Nunca el contenido, nunca quien lo visito: solo "este dominio tiene un modelo
# detras". Por eso la base puede crecer sola sin comprometer a nadie.

# Cuanto dura un veredicto antes de que convenga volver a mirarlo. No es un
# numero fijo: depende de que tan solido fue el veredicto (ver ttl_for).
TTL_ALTA_CONFIANZA = 30 * 24 * 3600
TTL_FRAGIL = 48 * 3600
UMBRAL_CONFIANZA_ALTA = 0.8


@dataclass(frozen=True)
class Verdict:
    domain: str
    classification: str  # ai_unapproved | non_ai
    kind: str  # llm_chat | llm_api | ai_feature | non_ai
    confidence: float
    evidence: str
    source: str  # seed_list | llm_classifier | heuristic | manual_review
    classified_at: float

    def as_response(self) -> dict:
        payload = asdict(self)
        payload["classified_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.classified_at)
        )
        payload["ttl_seconds"] = ttl_for(self)
        return payload


def ttl_for(verdict: Verdict) -> int | None:
    """Cuanto puede durar `verdict` antes de que convenga volver a mirarlo.

    Un veredicto que el modelo vio con confianza alta es solido: 30 dias. Uno
    que se decidio casi por el nombre -- el sitio no respondio, o la
    confianza quedo pegada al umbral -- es el mas fragil que produce el
    sistema, y no deberia sobrevivir mas de un par de dias. Uno que un humano
    reviso en el panel no lo pisa nada automatico: None significa que nunca
    vence.
    """

    if verdict.source == "manual_review":
        ttl: int | None = None
    else:
        if verdict.source == "llm_classifier" and verdict.confidence >= UMBRAL_CONFIANZA_ALTA:
            ttl = TTL_ALTA_CONFIANZA
        else:
            ttl = TTL_FRAGIL
    return ttl


def vencido(verdict: Verdict, ahora: float) -> bool:
    """Si `verdict` ya paso su TTL y conviene volver a investigarlo."""

    ttl = ttl_for(verdict)
    return ttl is not None and (ahora - verdict.classified_at) > ttl


class DomainStore:
    """Veredictos compartidos, persistidos en disco.

    Un JSON alcanza para el MVP y para la demo. Lo que importa acá no es el motor
    de almacenamiento sino la regla: un dominio se investiga **una vez** en toda
    la red de clientes y el resultado se reparte.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._verdicts: dict[str, Verdict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self._verdicts = {
                domain: Verdict(**data) for domain, data in raw.items()
            }

    def _flush(self) -> None:
        payload = {domain: asdict(v) for domain, v in self._verdicts.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, domain: str) -> Verdict | None:
        with self._lock:
            return self._verdicts.get(domain.lower().strip("."))

    def put(self, verdict: Verdict) -> Verdict:
        with self._lock:
            self._verdicts[verdict.domain] = verdict
            self._flush()
        return verdict

    def count(self) -> int:
        with self._lock:
            return len(self._verdicts)

    def all_domains(self) -> list[str]:
        with self._lock:
            return sorted(self._verdicts)


class PolicyStore:
    """Politicas por tenant, persistidas en disco.

    Va separada de DomainStore porque no comparten forma ni ciclo de vida: un
    veredicto de dominio se acumula uno a uno y con un esquema fijo (Verdict);
    una politica la escribe el panel entera de una vez, como el JSON que le
    mande el cliente, y su forma la define agent/aegis_agent/policy.py, no
    este archivo. Guardar un dict crudo por tenant evita que el backend tenga
    que conocer los campos de Policy para poder persistirla.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._policies: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._policies = json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._policies, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def get(self, tenant: str) -> dict:
        with self._lock:
            return self._policies.get(tenant, {})

    def put(self, tenant: str, datos: dict) -> dict:
        with self._lock:
            self._policies[tenant] = datos
            self._flush()
        return datos
