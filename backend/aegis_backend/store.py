from __future__ import annotations

import calendar
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import supabase

# Lo unico compartido entre todos los clientes es el veredicto de un dominio.
# Nunca el contenido, nunca quien lo visito: solo "este dominio tiene un modelo
# detras". Por eso la base puede crecer sola sin comprometer a nadie.
#
# LOS DOS ALMACENES NO PERSISTEN IGUAL, Y ES A PROPOSITO.
#
# `DomainStore` y `SupabaseDomainStore` son dos implementaciones del mismo
# contrato y se elige una al construir: o JSON local, o la tabla compartida. Un
# veredicto se investiga una vez en toda la red y se reparte, asi que tener las
# dos a la vez escribiendo lo mismo no agrega nada y esconde cual mando.
#
# `PolicyStore` si escribe en los dos lados, porque responde a otra pregunta.
# No es un dato que la red comparte: es lo que ESTA empresa configuro a mano, y
# si se pierde se nota al dia siguiente. El JSON local es ademas lo que permite
# levantar el backend sin credenciales de nada.

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


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _epoch(marca: str) -> float:
    return calendar.timegm(time.strptime(marca[:19], "%Y-%m-%dT%H:%M:%S"))


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

    def desde(self, marca: str) -> list[Verdict]:
        """Veredictos vistos u actualizados desde `marca` (ISO 8601).

        Sirve GET /v1/domains/sync tanto con este store como con
        SupabaseDomainStore, sin que el endpoint tenga que saber cual de los
        dos esta atras.
        """

        umbral = _epoch(marca)
        with self._lock:
            return sorted(
                (v for v in self._verdicts.values() if v.classified_at >= umbral),
                key=lambda v: v.classified_at,
            )


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


REQUEST_TIMEOUT = 8


def _fila_a_verdict(fila: dict) -> Verdict:
    return Verdict(
        domain=fila["dominio"],
        classification=fila.get("clasificacion", ""),
        kind=fila.get("tipo", ""),
        confidence=float(fila.get("confianza") or 0),
        evidence=fila.get("evidencia", ""),
        source=fila.get("fuente", ""),
        classified_at=_epoch(fila["clasificado_en"]),
    )


def _verdict_a_fila(verdict: Verdict) -> dict:
    ttl = ttl_for(verdict)
    return {
        "dominio": verdict.domain,
        "clasificacion": verdict.classification,
        "tipo": verdict.kind,
        "confianza": verdict.confidence,
        "evidencia": verdict.evidence,
        "fuente": verdict.source,
        "clasificado_en": _iso(verdict.classified_at),
        "vence_en": _iso(verdict.classified_at + ttl) if ttl is not None else None,
    }


class SupabaseDomainStore:
    """El mismo contrato que DomainStore, pero via PostgREST sobre Supabase.

    Es la fuente de verdad compartida entre todos los clientes de la red, no
    el camino critico: la comparacion de cada request sigue siendo local (ver
    suffixes.py). Esto solo tiene que ser rapido para sincronizar, no para
    decidir. Sin dependencias nuevas: PostgREST se habla con urllib, igual que
    el resto del backend.

    Cualquier falla de red degrada, nunca lanza: un dominio que no se puede
    consultar queda para la heuristica local, y un dominio que no se pudo
    guardar se reintenta en la proxima clasificacion. La base compartida
    nunca puede tumbar a un cliente.
    """

    def __init__(self, url: str, service_key: str) -> None:
        self._url = f"{url.rstrip('/')}/rest/v1/dominios"
        self._headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, query: str = "", *, headers=None, body=None):
        peticion = urllib.request.Request(
            self._url + query,
            data=json.dumps(body).encode() if body is not None else None,
            headers={**self._headers, **(headers or {})},
            method=method,
        )
        with urllib.request.urlopen(peticion, timeout=REQUEST_TIMEOUT) as respuesta:
            crudo = respuesta.read()
            filas = json.loads(crudo) if crudo else []
            cabeceras = respuesta.headers
        return filas, cabeceras

    def get(self, domain: str) -> Verdict | None:
        domain = domain.lower().strip(".")
        try:
            filas, _ = self._request("GET", f"?dominio=eq.{domain}&select=*")
        except (urllib.error.URLError, OSError, ValueError):
            filas = []
        return _fila_a_verdict(filas[0]) if filas else None

    def put(self, verdict: Verdict) -> Verdict:
        try:
            self._request(
                "POST",
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                body=[_verdict_a_fila(verdict)],
            )
        except (urllib.error.URLError, OSError, ValueError):
            # La proxima vez que se investigue este dominio se vuelve a
            # intentar guardar. Un fallo de red aca no puede tumbar al
            # backend que esta protegiendo al resto de la red.
            pass
        return verdict

    def count(self) -> int:
        try:
            _, cabeceras = self._request(
                "GET", "?select=dominio", headers={"Prefer": "count=exact"}
            )
        except (urllib.error.URLError, OSError, ValueError):
            resultado = 0
        else:
            rango = cabeceras.get("Content-Range", "")
            resultado = int(rango.split("/")[-1]) if "/" in rango else 0
        return resultado

    def all_domains(self) -> list[str]:
        try:
            filas, _ = self._request("GET", "?select=dominio&order=dominio")
        except (urllib.error.URLError, OSError, ValueError):
            filas = []
        return sorted(fila["dominio"] for fila in filas)

    def desde(self, marca: str) -> list[Verdict]:
        """Veredictos actualizados desde `marca` (ISO 8601), para GET /v1/domains/sync."""

        try:
            filas, _ = self._request(
                "GET", f"?actualizado_en=gte.{marca}&select=*&order=actualizado_en"
            )
        except (urllib.error.URLError, OSError, ValueError):
            filas = []
        return [_fila_a_verdict(fila) for fila in filas]


def store_from_env(ruta_json: Path) -> DomainStore | SupabaseDomainStore:
    """Supabase si esta configurado; si no, el store de JSON de siempre.

    Nada del resto del backend necesita saber cual de los dos esta atras: los
    dos cumplen el mismo contrato (get/put/count/all_domains/desde).
    """

    url = os.environ.get("SUPABASE_URL")
    clave = os.environ.get("SUPABASE_SERVICE_KEY")
    if url and clave:
        resultado: DomainStore | SupabaseDomainStore = SupabaseDomainStore(url, clave)
    else:
        resultado = DomainStore(ruta_json)
    return resultado
