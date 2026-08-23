from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, replace

# Clasificar por el nombre del dominio no alcanza y nunca iba a alcanzar:
# monica.im, coze.com o poe.com no dicen nada, y hay negocios legitimos con "ai"
# en el nombre. Para decidir hay que mirar el sitio.
#
# Lo que se descarga aca es la portada publica del dominio, la misma que ve
# cualquiera que lo visite. No hay ni un dato del usuario en este archivo, y esa
# es la razon por la que esto puede vivir en el backend.

TIMEOUT = 8
MAX_BYTES = 200_000
SNIPPET_CHARS = 1200

# Debajo de esto la portada es un SPA vacio: casi nada para que Haiku lea, y el
# clasificador cae a la heuristica del nombre, el veredicto mas fragil que
# produce el sistema. Vale la pena sondear un poco mas.
UMBRAL_PORTADA_DELGADA = 200

PROBE_TIMEOUT = 5
PROBE_MAX_BYTES = 20_000

_UA = "AegisBot/0.1 (clasificador de dominios; contacto: seguridad@aegis.example)"

_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DESCRIPCION = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S
)
_ETIQUETAS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")

# Rutas que un endpoint de IA suele exponer, para leer del robots.txt. No hace
# falta el listado completo de policy.AI_PATH_HINTS: alcanza con lo que
# aparece en un robots.txt real, que casi nunca lista rutas en espanol.
_RUTAS_DE_IA = re.compile(
    r"/[\w./-]*(?:chat|completion|complet|v1/messages|generate|assistant|"
    r"inference|predict|invocations)[\w./-]*",
    re.I,
)


@dataclass(frozen=True)
class Evidence:
    domain: str
    reachable: bool
    title: str = ""
    description: str = ""
    snippet: str = ""
    error: str = ""
    # Lo que encontraron las sondas cuando la portada vino delgada. Ver
    # probe_evidence() mas abajo.
    sondas: str = ""

    def as_text(self) -> str:
        return "\n".join(
            parte
            for parte in (
                f"Titulo: {self.title}" if self.title else "",
                f"Descripcion: {self.description}" if self.description else "",
                f"Texto de la portada: {self.snippet}" if self.snippet else "",
                self.sondas,
            )
            if parte
        )


def _limpiar(texto: str) -> str:
    return _ESPACIOS.sub(" ", texto).strip()


def _get(url: str) -> str | None:
    """Cuerpo de texto de `url`, o None si no respondio o no valio la pena leer."""

    peticion = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(peticion, timeout=PROBE_TIMEOUT) as respuesta:
            crudo = respuesta.read(PROBE_MAX_BYTES)
    except (urllib.error.URLError, OSError, ValueError):
        crudo = None
    return crudo.decode("utf-8", errors="replace") if crudo else None


def _probe_ai_plugin(domain: str) -> str:
    # Casi ningun sitio que no sea un plugin de IA publica esto. Si esta,
    # alcanza: no hace falta gastar las otras tres sondas.
    crudo = _get(f"https://{domain}/.well-known/ai-plugin.json")
    return (
        "Publica un ai-plugin.json: se declara como un plugin de IA."
        if crudo is not None
        else ""
    )


def _probe_manifest(domain: str) -> str:
    crudo = _get(f"https://{domain}/manifest.json")
    resultado = ""
    if crudo is not None:
        try:
            datos = json.loads(crudo)
        except ValueError:
            datos = {}
        nombre = str(datos.get("name") or datos.get("short_name") or "")
        descripcion = str(datos.get("description") or "")
        texto = " - ".join(parte for parte in (nombre, descripcion) if parte)
        if texto:
            resultado = f"El manifest.json dice: {_limpiar(texto)[:200]}"
    return resultado


def _probe_robots(domain: str) -> str:
    crudo = _get(f"https://{domain}/robots.txt")
    resultado = ""
    if crudo is not None:
        rutas = sorted({m.group(0) for m in _RUTAS_DE_IA.finditer(crudo)})
        if rutas:
            resultado = f"El robots.txt lista rutas de IA: {', '.join(rutas[:5])}"
    return resultado


def _probe_openapi(domain: str) -> str:
    crudo = _get(f"https://{domain}/openapi.json")
    resultado = ""
    if crudo is not None:
        try:
            datos = json.loads(crudo)
        except ValueError:
            datos = {}
        rutas = sorted((datos.get("paths") or {}).keys())[:10]
        if rutas:
            resultado = f"El openapi.json declara rutas: {', '.join(rutas)}"
    return resultado


def probe_evidence(domain: str) -> str:
    """Sondea rutas publicas cuando la portada no dijo nada.

    Se corta apenas aparece ai-plugin.json: es prueba casi definitiva y no
    hace falta gastar las otras tres sondas. Las demas ni bloquean ni
    condenan por si solas -- se acumulan y el que decide es Haiku, con todo
    lo que se junto.
    """

    definitivo = _probe_ai_plugin(domain)
    if definitivo:
        resultado = definitivo
    else:
        piezas = [
            pieza
            for pieza in (_probe_manifest(domain), _probe_robots(domain), _probe_openapi(domain))
            if pieza
        ]
        resultado = "\n".join(piezas)
    return resultado


def fetch(domain: str) -> Evidence:
    """Descarga la portada publica del dominio y extrae lo legible."""

    peticion = urllib.request.Request(
        f"https://{domain}/", headers={"User-Agent": _UA, "Accept": "text/html"}
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            crudo = respuesta.read(MAX_BYTES)
        html = crudo.decode("utf-8", errors="replace")
        titulo = _TITULO.search(html)
        descripcion = _DESCRIPCION.search(html)
        cuerpo = _HTML.sub(" ", _ETIQUETAS.sub(" ", html))
        evidencia = Evidence(
            domain=domain,
            reachable=True,
            title=_limpiar(titulo.group(1))[:200] if titulo else "",
            description=_limpiar(descripcion.group(1))[:300] if descripcion else "",
            snippet=_limpiar(cuerpo)[:SNIPPET_CHARS],
        )
        if len(evidencia.snippet) < UMBRAL_PORTADA_DELGADA:
            sondas = probe_evidence(domain)
            if sondas:
                evidencia = replace(evidencia, sondas=sondas)
    except (urllib.error.URLError, OSError, ValueError) as error:
        # Un dominio que no responde no se condena ni se absuelve: queda para la
        # heuristica del nombre y con la confianza que eso merece.
        evidencia = Evidence(domain=domain, reachable=False, error=str(error)[:120])
    return evidencia
