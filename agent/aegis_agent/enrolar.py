"""Sumar este equipo al panel de una empresa, con un codigo.

## Por que hace falta

El instalador configuraba el proxy, la CA y las variables de los CLIs, y nunca
`AEGIS_EVENTS_URL`. O sea: alguien instalaba Aegis, quedaba protegido, y **no le
hablaba a ningun panel**. Los eventos se acumulaban en un archivo local que nadie
iba a abrir, y la empresa veia su panel vacio y concluia que nadie usa IA.

Del otro lado el agujero era simetrico: `/v1/events` no pedia credencial, asi que
cualquiera con la URL podia escribir en el panel de cualquier empresa.

Las dos mitades se cierran con un codigo que el admin genera en el panel y la
persona pega una vez.

## Las decisiones

**El codigo se canjea una sola vez.** Lo que queda guardado no es el codigo sino
el token de equipo que el panel devuelve a cambio. Asi el codigo se puede mandar
por chat sin que sirva para leer nada, y un equipo ya enrolado no depende de que
el codigo siga vivo.

**Se guarda en el entorno del USUARIO, junto a las demas.** No en un archivo
propio: el agente ya lee su configuracion de ahi (ver install/windows.py), y un
segundo lugar donde mirar es un segundo lugar donde olvidarse de limpiar al
desinstalar.

**Enrolar NO instala nada.** Se puede correr antes o despues de instalar, y
volver a correrlo cambia de empresa sin tocar el proxy ni la CA. Son dos
decisiones distintas -- proteger este equipo, y a quien reportarle -- y
mezclarlas obliga a desinstalar para cambiar de panel.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

TIMEOUT = 15

# Donde vive el panel al que se le pide el canje. Se puede apuntar a otro para
# probar contra un backend local sin tocar codigo.
PANEL_POR_DEFECTO = "https://aegis-panel.onrender.com"

# Las tres que dejan al agente conectado. Van juntas a proposito: configurar la
# URL sin el token deja un agente que manda eventos que el panel rechaza, y el
# token sin la URL no manda nada. Un estado a medias es peor que ninguno.
VARIABLES = ("AEGIS_EVENTS_URL", "AEGIS_EVENTS_TOKEN", "AEGIS_BACKEND")


def canjear(codigo: str, panel: str = "") -> tuple[bool, dict | str]:
    """Le pide al panel el token de equipo. (True, datos) o (False, motivo)."""

    base = (panel or os.environ.get("AEGIS_PANEL", PANEL_POR_DEFECTO)).rstrip("/")
    cuerpo = json.dumps({"codigo": codigo}).encode("utf-8")
    peticion = urllib.request.Request(
        f"{base}/v1/enrolar",
        data=cuerpo,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            return True, json.loads(respuesta.read())
    except urllib.error.HTTPError as error:
        # 400 es el unico esperado y significa una cosa sola: el codigo no
        # sirve. Se traduce a algo que una persona pueda accionar.
        if error.code == 400:
            return False, (
                "Ese codigo no sirve. Puede estar vencido, revocado, o mal "
                "copiado: son cuatro letras o numeros, un guion, y otros cuatro."
            )
        return False, f"El panel contesto {error.code}."
    except (urllib.error.URLError, OSError, ValueError) as error:
        return False, f"No se pudo hablar con el panel ({base}): {error}"


def guardar(datos: dict) -> None:
    """Deja las tres variables en el entorno del usuario y en este proceso."""

    from .install import windows

    valores = {
        "AEGIS_EVENTS_URL": datos.get("eventos_url", ""),
        "AEGIS_EVENTS_TOKEN": datos.get("token", ""),
        "AEGIS_BACKEND": datos.get("backend_url", ""),
    }
    windows.escribir_variables(valores)
    # Tambien en el proceso actual, para que `aegis estado` justo despues no
    # tenga que esperar a que Windows propague el cambio.
    os.environ.update(valores)


def olvidar() -> None:
    """Desconecta este equipo del panel. Lo llama el desinstalador."""

    from .install import windows

    windows.borrar_variables(VARIABLES)
    for nombre in VARIABLES:
        os.environ.pop(nombre, None)


def estado() -> dict:
    """A que panel reporta este equipo, si es que reporta a alguno."""

    url = os.environ.get("AEGIS_EVENTS_URL", "").strip()
    token = os.environ.get("AEGIS_EVENTS_TOKEN", "").strip()
    return {
        "conectado": bool(url and token),
        "panel": url,
        # A medias es un estado real y hay que poder nombrarlo: con URL y sin
        # token el agente manda eventos que el panel rechaza uno por uno, en
        # silencio, y desde afuera se ve igual que "nadie usa IA".
        "a_medias": bool(url) != bool(token),
    }
