from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .suffixes import most_specific_match

# Cliente de la base colaborativa. Dos reglas gobiernan este archivo:
#
#   1. Nunca bloquea el camino critico. Si el veredicto no esta en el cache
#      local, el agente decide con su politica y la consulta viaja aparte.
#   2. Lo unico que sale de aca es un nombre de dominio. No hay una sola linea
#      que pueda mandar contenido, y eso es a proposito.

DEFAULT_CACHE = Path(os.environ.get("AEGIS_DOMAIN_CACHE", "aegis-domains-cache.json"))
DEFAULT_BACKEND = os.environ.get("AEGIS_BACKEND", "http://127.0.0.1:8686")
REQUEST_TIMEOUT = 5

# Esperas entre reintentos mientras el backend clasifica. La ultima es larga a
# proposito: si en cuatro segundos no hubo veredicto, lo tendra la proxima visita.
RETRY_BACKOFF = (0.3, 0.7, 1.5, 0)

# Cada cuanto se sincroniza el delta con el backend. Nunca esta en el camino
# de ninguna decision (la comparacion es local, ver suffixes.py), asi que
# puede ser tan espaciado como haga falta.
INTERVALO_SYNC = 300
DESDE_EL_ORIGEN = "1970-01-01T00:00:00Z"


class DomainClient:
    def __init__(
        self,
        backend: str = DEFAULT_BACKEND,
        cache_path: Path = DEFAULT_CACHE,
        enabled: bool = True,
    ) -> None:
        self.backend = backend.rstrip("/")
        # Se relee del entorno en cada instancia para que el proceso del proxy
        # pueda apuntar a otro cache sin recargar el modulo.
        self.cache_path = Path(os.environ.get("AEGIS_DOMAIN_CACHE", str(cache_path)))
        self.enabled = enabled
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        self._in_flight: set[str] = set()
        self._ultima_sincronizacion = DESDE_EL_ORIGEN
        self._load()

    # -- cache --------------------------------------------------------------

    def _load(self) -> None:
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8") or "{}")
            except (json.JSONDecodeError, OSError):
                # Un cache corrupto no puede tumbar el agente: se descarta y se
                # vuelve a llenar solo.
                self._cache = {}

    def _save(self) -> None:
        try:
            self.cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _normalize(self, domain: str) -> str:
        return domain.lower().strip(".")

    # -- consulta -----------------------------------------------------------

    def cached(self, domain: str) -> str | None:
        """Clasificacion conocida para el dominio, sin tocar la red.

        Camina por sufijos (ver suffixes.py) para que un veredicto sobre
        acme.com cubra tambien chat.acme.com: el shadow AI de una empresa
        casi siempre vive bajo el mismo dominio padre, y no hay que
        reinvestigar cada subdominio nuevo desde cero.
        """

        with self._lock:
            match = most_specific_match(self._normalize(domain), self._cache)
            entrada = self._cache.get(match) if match else None
        return entrada.get("classification") if entrada else None

    def evidence(self, domain: str) -> str:
        with self._lock:
            entrada = self._cache.get(self._normalize(domain))
        return entrada.get("evidence", "") if entrada else ""

    def request_classification(self, domain: str) -> None:
        """Pide el veredicto en segundo plano. Nunca espera la respuesta."""

        domain = self._normalize(domain)
        if self.enabled:
            with self._lock:
                arrancar = domain not in self._cache and domain not in self._in_flight
                if arrancar:
                    self._in_flight.add(domain)
            if arrancar:
                threading.Thread(target=self._fetch, args=(domain,), daemon=True).start()

    def _fetch(self, domain: str) -> None:
        try:
            for espera in RETRY_BACKOFF:
                datos = self._ask(domain)
                # 202 significa "lo estoy clasificando". Se reintenta con espera
                # creciente porque el hilo esta fuera del camino critico: nadie
                # esta esperando esto para poder trabajar.
                if datos is not None and datos.get("classification") not in (None, "pending"):
                    self._remember(domain, datos)
                    break
                time.sleep(espera)
        finally:
            with self._lock:
                self._in_flight.discard(domain)

    def _ask(self, domain: str) -> dict | None:
        try:
            peticion = urllib.request.Request(f"{self.backend}/v1/domains/{domain}")
            with urllib.request.urlopen(peticion, timeout=REQUEST_TIMEOUT) as respuesta:
                datos = json.loads(respuesta.read())
        except (urllib.error.URLError, OSError, ValueError):
            # Backend caido o respuesta rara: el agente sigue protegiendo con lo
            # que tiene. La ausencia de veredicto nunca es un permiso.
            datos = None
        return datos

    def _remember(self, domain: str, datos: dict) -> None:
        with self._lock:
            self._cache[domain] = {
                "classification": datos.get("classification", ""),
                "kind": datos.get("kind", ""),
                "confidence": datos.get("confidence", 0),
                "evidence": datos.get("evidence", ""),
                "source": datos.get("source", ""),
            }
            self._save()

    # -- sincronizacion -------------------------------------------------------

    def sincronizar(self) -> None:
        """Baja el delta del backend desde la ultima sincronizacion y lo mezcla.

        Es lo que mantiene la lista negra al dia sin que la comparacion del
        camino critico tenga que tocar la red nunca (esa sigue siendo
        instantanea y 100% local, ver suffixes.py). Sin red, no lanza: el
        cache en disco queda tal cual estaba, que es lo unico que garantiza
        el ADR 0003.
        """

        if self.enabled:
            try:
                peticion = urllib.request.Request(
                    f"{self.backend}/v1/domains/sync?desde={self._ultima_sincronizacion}"
                )
                with urllib.request.urlopen(peticion, timeout=REQUEST_TIMEOUT) as respuesta:
                    datos = json.loads(respuesta.read())
            except (urllib.error.URLError, OSError, ValueError):
                datos = None
            if datos is not None:
                with self._lock:
                    for veredicto in datos.get("dominios", []):
                        dominio = self._normalize(veredicto.get("domain", ""))
                        if dominio:
                            self._cache[dominio] = {
                                "classification": veredicto.get("classification", ""),
                                "kind": veredicto.get("kind", ""),
                                "confidence": veredicto.get("confidence", 0),
                                "evidence": veredicto.get("evidence", ""),
                                "source": veredicto.get("source", ""),
                            }
                    self._save()
                self._ultima_sincronizacion = datos.get(
                    "hasta", self._ultima_sincronizacion
                )

    def sincronizar_en_segundo_plano(self) -> None:
        """Bucle de fondo: sincroniza al arrancar y despues cada INTERVALO_SYNC."""

        while True:
            self.sincronizar()
            time.sleep(INTERVALO_SYNC)

    # -- utilidades ---------------------------------------------------------

    def known_domains(self) -> list[str]:
        with self._lock:
            return sorted(self._cache)
