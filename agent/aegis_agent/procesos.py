"""Que aplicacion abrio esta conexion.

Hasta aca todos los eventos decian `process: "browser"`, incluso cuando el
envio venia de Claude Code. El contrato de datos pide ese campo desde el primer
dia y estaba mintiendo, asi que el panel no podia distinguir a una persona
pegando un fragmento en el navegador de un agente mandando un repositorio
entero. En 2026 esa es la diferencia que importa.

**Esto no le llega al motor de deteccion**, y es a proposito: el ADR 0002 dice
que el detector recibe texto y un destino, nada mas, porque es lo que hace que
el mismo codigo cubra ChatGPT en el navegador, un IDE y una app que todavia no
existe. Lo que se atribuye aca es para el evento y para la politica, dos capas
mas arriba.

Como se resuelve: mitmproxy conoce el puerto efimero del cliente, y la tabla de
conexiones del sistema dice que proceso lo tiene abierto. Leerla cuesta unos
3 ms sobre 341 conexiones, medido en la maquina de desarrollo. Eso es barato una
vez por conexion TCP y caro una vez por request, asi que se resuelve cuando la
conexion se abre y se guarda; con keep-alive, una sesion entera de un CLI paga
una sola lectura.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# Cuanto vale una lectura de la tabla. Existe para que una rafaga de conexiones
# simultaneas (abrir una pagina con veinte recursos) comparta una sola lectura.
VENTANA_DE_TABLA = 2.0

DESCONOCIDO = "desconocido"

# Interpretes que no dicen nada por su nombre: media docena de herramientas de IA
# son un node.exe. Para estos, y solo para estos, se mira la linea de comandos,
# que es mas cara de leer.
_INTERPRETES = frozenset(
    {"node.exe", "node", "python.exe", "python", "python3", "python3.13",
     "deno.exe", "deno", "bun.exe", "bun", "ruby.exe", "ruby"}
)

# Marcas que identifican una herramienta, y como se va a llamar en el panel y en
# la politica. Se buscan primero en el nombre del ejecutable y, solo si el
# ejecutable es un interprete, en la linea de comandos.
#
# La normalizacion importa mas de lo que parece: la misma herramienta se instala
# distinto segun la maquina. Claude Code puede ser `claude.exe` en un equipo y
# `node.exe ...\cli.js` en otro, y una politica que dijera "claude.exe" solo
# funcionaria en el primero. Nombrandolos igual, la politica es portable.
_MARCAS = (
    ("claude", "claude-code"),
    ("codex", "codex"),
    ("cursor", "cursor"),
    ("copilot", "copilot"),
    ("aider", "aider"),
    ("ollama", "ollama"),
    ("chatgpt", "chatgpt-app"),
)


def normalizar(nombre: str, linea: str = "") -> str:
    """El nombre canonico de la herramienta, o el del ejecutable tal cual."""

    minusculas = (nombre or "").lower()
    resultado = nombre or DESCONOCIDO
    for marca, canonico in _MARCAS:
        if marca in minusculas:
            resultado = canonico
            break
    else:
        if minusculas in _INTERPRETES:
            for marca, canonico in _MARCAS:
                if marca in (linea or "").lower():
                    resultado = canonico
                    break
    return resultado


@dataclass(frozen=True)
class Proceso:
    nombre: str = DESCONOCIDO
    ruta: str = ""
    pid: int = 0

    @property
    def conocido(self) -> bool:
        return self.nombre != DESCONOCIDO


_tabla: dict[int, int] = {}
_leida_en: float = 0.0
_por_pid: dict[int, Proceso] = {}


def _psutil():
    try:
        import psutil
    except ImportError:
        psutil = None
    return psutil


def _refrescar_tabla(ahora: float) -> None:
    """Puerto local -> pid, para las conexiones que salen de esta maquina.

    Nunca lanza. Sin psutil o sin permisos no hay atribucion, y eso degrada el
    panel; no puede degradar la proteccion.
    """

    global _tabla, _leida_en

    psutil = _psutil()
    nueva: dict[int, int] = {}
    if psutil is not None:
        try:
            for conexion in psutil.net_connections(kind="tcp"):
                if conexion.pid and conexion.laddr:
                    nueva[conexion.laddr.port] = conexion.pid
        except Exception:
            # En Windows enumerar procesos ajenos puede dar AccessDenied segun
            # como se lanzo el agente.
            nueva = {}
    _tabla = nueva
    _leida_en = ahora


def _nombre_util(pid: int) -> tuple[str, str]:
    """(nombre, ruta) del proceso, desambiguando los interpretes."""

    psutil = _psutil()
    nombre, ruta = DESCONOCIDO, ""
    if psutil is not None:
        try:
            proceso = psutil.Process(pid)
            nombre = proceso.name() or DESCONOCIDO
            try:
                ruta = proceso.exe() or ""
            except Exception:
                ruta = ""
            nombre = normalizar(nombre, _linea_de_comandos(proceso, nombre))
        except Exception:
            nombre, ruta = DESCONOCIDO, ""
    return nombre, ruta


def _linea_de_comandos(proceso, nombre: str) -> str:
    """La linea de comandos, solo cuando hace falta.

    Leerla cuesta bastante mas que el nombre y solo aporta cuando el ejecutable
    no dice nada: media docena de herramientas de IA son un node.exe.
    """

    linea = ""
    if (nombre or "").lower() in _INTERPRETES:
        try:
            linea = " ".join(proceso.cmdline())
        except Exception:
            linea = ""
    return linea


def del_puerto(puerto: int, ahora: float | None = None) -> Proceso:
    """El proceso duenio de ese puerto local, o uno desconocido.

    Devolver "desconocido" es una respuesta valida y frecuente: la conexion pudo
    cerrarse entre que llego el request y que se miro la tabla. Nada de lo que
    decide Aegis puede depender de que esto acierte.
    """

    ahora = time.time() if ahora is None else ahora
    if ahora - _leida_en > VENTANA_DE_TABLA:
        _refrescar_tabla(ahora)

    pid = _tabla.get(puerto)
    if pid is None:
        # Un puerto que no estaba en la lectura anterior puede ser una conexion
        # nueva: vale releer una vez, pero solo una.
        _refrescar_tabla(ahora)
        pid = _tabla.get(puerto)

    if pid is None:
        proceso = Proceso()
    else:
        if pid not in _por_pid:
            nombre, ruta = _nombre_util(pid)
            _por_pid[pid] = Proceso(nombre=nombre, ruta=ruta, pid=pid)
        proceso = _por_pid[pid]
    return proceso


def olvidar() -> None:
    """Vacia los caches. Para los tests, y por si el agente corre muchas horas."""

    global _tabla, _leida_en
    _tabla = {}
    _leida_en = 0.0
    _por_pid.clear()
