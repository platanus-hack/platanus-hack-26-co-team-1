from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import supabase

# Lo unico compartido entre todos los clientes es el veredicto de un dominio.
# Nunca el contenido, nunca quien lo visito: solo "este dominio tiene un modelo
# detras". Por eso la base puede crecer sola sin comprometer a nadie.
#
# Los dos almacenes de este archivo guardan en JSON y, si hay Supabase
# configurado, tambien alla. El JSON no sobra: es lo que hace que el backend
# arranque sin credenciales de nada, y la red que atrapa a Supabase cuando no
# contesta.

DEFAULT_TTL = 7 * 24 * 3600


@dataclass(frozen=True)
class Verdict:
    domain: str
    classification: str  # ai_unapproved | non_ai
    kind: str  # llm_chat | llm_api | ai_feature | non_ai
    confidence: float
    evidence: str
    source: str  # seed_list | llm_classifier | heuristic | manual_review
    classified_at: float

    def as_response(self, ttl: int = DEFAULT_TTL) -> dict:
        payload = asdict(self)
        payload["classified_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.classified_at)
        )
        payload["ttl_seconds"] = ttl
        return payload


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

        remotos = supabase.leer_veredictos()
        if remotos:
            # Los remotos ganan: son los que vieron todos los clientes de la red,
            # y el JSON local es el cache de uno solo. Se filtra por los campos
            # de Verdict para que una columna nueva en la base no reviente el
            # arranque de un agente viejo.
            validos = {f.name for f in fields(Verdict)}
            for domain, datos in remotos.items():
                recortado = {k: v for k, v in datos.items() if k in validos}
                try:
                    self._verdicts[domain] = Verdict(**recortado)
                except TypeError:
                    # Una fila incompleta no puede dejar sin veredictos al resto.
                    pass

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
        # Fuera del lock: subir es una llamada de red y ningun otro cliente
        # tiene por que esperarla para leer un veredicto que ya esta en memoria.
        supabase.guardar_veredicto(asdict(verdict))
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

        remotas = supabase.leer_politicas()
        if remotas:
            self._policies.update(remotas)

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
        # La politica es lo unico de todo esto que si se pierde se nota al dia
        # siguiente: es lo que la empresa escribio a mano en el panel.
        supabase.guardar_politica(tenant, datos)
        return datos
