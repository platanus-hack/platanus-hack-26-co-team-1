from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

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

_UA = "AegisBot/0.1 (clasificador de dominios; contacto: seguridad@aegis.example)"

_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DESCRIPCION = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.I | re.S
)
_ETIQUETAS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)
_HTML = re.compile(r"<[^>]+>")
_ESPACIOS = re.compile(r"\s+")


@dataclass(frozen=True)
class Evidence:
    domain: str
    reachable: bool
    title: str = ""
    description: str = ""
    snippet: str = ""
    error: str = ""

    def as_text(self) -> str:
        return "\n".join(
            parte
            for parte in (
                f"Titulo: {self.title}" if self.title else "",
                f"Descripcion: {self.description}" if self.description else "",
                f"Texto de la portada: {self.snippet}" if self.snippet else "",
            )
            if parte
        )


def _limpiar(texto: str) -> str:
    return _ESPACIOS.sub(" ", texto).strip()


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
    except (urllib.error.URLError, OSError, ValueError) as error:
        # Un dominio que no responde no se condena ni se absuelve: queda para la
        # heuristica del nombre y con la confianza que eso merece.
        evidencia = Evidence(domain=domain, reachable=False, error=str(error)[:120])
    return evidencia
