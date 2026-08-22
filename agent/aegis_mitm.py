"""Punto de entrada para mitmproxy.

mitmproxy carga los scripts por ruta de archivo, no como modulos, asi que un
archivo con imports relativos revienta al cargarse. Este envoltorio hace el
import absoluto y deja el paquete intacto.

    mitmdump -s aegis_mitm.py
"""

from aegis_agent.proxy.addon import Aegis

addons = [Aegis()]
