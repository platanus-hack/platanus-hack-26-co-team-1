from __future__ import annotations

import socket
import threading
from dataclasses import dataclass

# Capa D del ADR 0001: lo que el proxy no puede ver.
#
# El proxy funciona porque las aplicaciones consultan VOLUNTARIAMENTE donde esta
# configurado: el navegador y Electron leen el registro de Windows, y los CLIs
# leen HTTP_PROXY. Nadie las obliga. Una aplicacion con su propio stack de red,
# o que habla QUIC sobre UDP, abre un socket directo a la IP de destino y ni se
# entera de que Aegis existe.
#
# Lo que si se puede hacer sin un driver es NOTARLO, y de ahi sale este sensor:
#
#   una aplicacion que usa el proxy se conecta a 127.0.0.1
#   una aplicacion que lo esquiva se conecta a la IP remota
#
# Esa diferencia se lee de la tabla de conexiones del sistema y no necesita
# interceptar nada. No es una heuristica: es la definicion de estar pasando por
# el proxy.
#
# El sensor no guarda nada en disco. Un registro de a que se conecta cada
# persona seria justo el archivo que este producto promete no tener.

PUERTOS_DE_INTERES = (443, 8443)

# Cada cuanto se mira la tabla. Va lento a proposito: esto no esta en el camino
# de ninguna decision y no tiene por que competir por CPU con el proxy.
INTERVALO_SEGUNDOS = 10


@dataclass(frozen=True)
class PuntoCiego:
    """Una conexion a una IA que no paso por Aegis."""

    proceso: str
    pid: int
    ip: str
    puerto: int
    host: str


def _conexiones_del_sistema():
    """Conexiones TCP establecidas, con el proceso que las abrio.

    psutil es opcional: si no esta, el sensor no funciona pero el agente si.
    Igual que con el modelo local, nada de esto puede ser un requisito.
    """

    try:
        import psutil
    except ImportError:
        conexiones = []
    else:
        try:
            conexiones = psutil.net_connections(kind="tcp")
        except Exception:
            # En Windows enumerar procesos ajenos puede dar AccessDenied segun
            # como se lanzo el agente. Sin permisos no hay sensor, no hay caida.
            conexiones = []
    return conexiones


def _nombre_del_proceso(pid: int) -> str:
    try:
        import psutil

        nombre = psutil.Process(pid).name()
    except Exception:
        nombre = f"pid {pid}"
    return nombre


def _es_local(ip: str) -> bool:
    return ip.startswith(("127.", "::1", "0.0.0.0")) or ip in ("", "localhost")


class SensorDePuntosCiegos:
    """Encuentra las aplicaciones que hablan con una IA sin pasar por Aegis.

    Recibe por parametro como saber si un host es de IA y como resolver una IP,
    para que se pueda probar sin red y para no atarlo al catalogo.
    """

    def __init__(
        self,
        pid_del_proxy: int,
        es_ia,
        resolver=None,
        conexiones=_conexiones_del_sistema,
    ) -> None:
        self.pid_del_proxy = pid_del_proxy
        self.es_ia = es_ia
        # None significa "no preguntes por la red": el mapa se llena con
        # cargar_catalogo y con lo que aprende del proxy, que es mas rapido y
        # mas certero que el DNS inverso.
        self.resolver = resolver
        self._conexiones = conexiones
        self._lock = threading.Lock()
        self._cache_de_ips: dict[str, str] = {}
        self._reportados: set[tuple[str, str]] = set()

    def _resolver_por_dns(self, ip: str) -> str:
        """De la IP al nombre, y casi siempre devuelve vacio.

        Existe solo como ultimo recurso. Medido contra la tabla real de esta
        maquina: 23 conexiones tardaron 28 SEGUNDOS en resolverse y ninguna dio
        el nombre del servicio, porque las IPs de un CDN no tienen registro
        inverso propio. Por eso el camino principal es al reves (ver
        cargar_catalogo) y esto queda apagado salvo que alguien lo pida.
        """

        try:
            nombre = socket.gethostbyaddr(ip)[0]
        except (OSError, socket.herror):
            nombre = ""
        return nombre

    def cargar_catalogo(self, dominios, resolver_hacia_adelante=None) -> int:
        """Resuelve los dominios de IA y se queda con sus IPs.

        Es la vuelta que hace que esto funcione. Preguntar "de quien es esta IP"
        no sirve: nadie publica el registro inverso de un CDN. Preguntar "que IPs
        tiene chat.openai.com" siempre contesta, y con eso alcanza para reconocer
        una conexion que va para alla.

        Corre una vez al arrancar, en segundo plano. Despues revisar() no hace
        una sola consulta de red.
        """

        buscar = resolver_hacia_adelante or self._ips_de_un_dominio
        aprendidas = 0
        for dominio in dominios:
            for ip in buscar(dominio):
                with self._lock:
                    if ip not in self._cache_de_ips:
                        aprendidas += 1
                    self._cache_de_ips[ip] = dominio
        return aprendidas

    @staticmethod
    def _ips_de_un_dominio(dominio: str) -> list[str]:
        try:
            direcciones = socket.gethostbyname_ex(dominio)[2]
        except (OSError, socket.herror, UnicodeError):
            direcciones = []
        return direcciones

    def host_de(self, ip: str) -> str:
        """Solo mira el mapa. No consulta la red, y por eso revisar() es instantaneo."""

        with self._lock:
            conocido = ip in self._cache_de_ips
            nombre = self._cache_de_ips.get(ip, "")
        if not conocido and self.resolver is not None:
            nombre = self.resolver(ip)
            with self._lock:
                self._cache_de_ips[ip] = nombre
        return nombre

    def aprender(self, ip: str, host: str) -> None:
        """Le ensena al sensor una IP que el proxy ya resolvio.

        Vale mucho mas que el DNS inverso: las IPs de un CDN casi nunca resuelven
        al nombre del servicio, y el proxy ya sabe a que host iba cada conexion
        que si paso por el.
        """

        with self._lock:
            self._cache_de_ips[ip] = host

    def revisar(self) -> list[PuntoCiego]:
        """Una pasada por la tabla de conexiones. Solo lo que no se reporto antes."""

        hallazgos: list[PuntoCiego] = []
        for conexion in self._conexiones():
            remoto = getattr(conexion, "raddr", None)
            pid = getattr(conexion, "pid", None)
            if remoto and pid and pid != self.pid_del_proxy:
                ip = getattr(remoto, "ip", "")
                puerto = getattr(remoto, "port", 0)
                if puerto in PUERTOS_DE_INTERES and not _es_local(ip):
                    punto = self._evaluar(pid, ip, puerto)
                    if punto is not None:
                        hallazgos.append(punto)
        return hallazgos

    def _evaluar(self, pid: int, ip: str, puerto: int) -> PuntoCiego | None:
        host = self.host_de(ip)
        punto = None
        if host and self.es_ia(host):
            clave = (str(pid), host)
            with self._lock:
                nuevo = clave not in self._reportados
                if nuevo:
                    self._reportados.add(clave)
            if nuevo:
                punto = PuntoCiego(
                    proceso=_nombre_del_proceso(pid),
                    pid=pid,
                    ip=ip,
                    puerto=puerto,
                    host=host,
                )
        return punto
