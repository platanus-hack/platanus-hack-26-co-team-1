from __future__ import annotations

import subprocess
from dataclasses import dataclass

# Cerrar la capa D sin escribir un driver.
#
# El sensor encuentra las aplicaciones que hablan con una IA sin pasar por Aegis.
# Esto es lo que se hace con esa informacion cuando la empresa elige cortar en
# vez de solo mirar (Policy.blind_spot_action).
#
# La idea no es interceptar lo que no se puede interceptar: es que, si no puede
# pasar por Aegis, no pase. La aplicacion se queda sin ruta directa y o bien
# vuelve al proxy del sistema, o bien no conecta. En los dos casos el dato no
# salio sin ser visto.
#
# UN DETALLE DE WINDOWS QUE DEFINE TODO ESTO: en el firewall de Windows las
# reglas de bloqueo le ganan a las de permitir. "Bloquear todo hacia estas IPs
# excepto el proxy" no se puede expresar: el bloqueo tambien alcanzaria al
# proxy y Aegis se cortaria a si mismo. Por eso se bloquea POR PROGRAMA, que
# ademas es mas preciso: se corta el camino directo del que se lo estaba
# saltando y no el de todo el mundo.

GRUPO = "Aegis"
PREFIJO = "Aegis - "

# Nombre reservado para la regla que mata QUIC. Esa si es global, y se puede:
# mitmproxy habla TCP, asi que bloquear UDP 443 hacia los servicios de IA no lo
# afecta y obliga al navegador a volver a TCP, que es por donde Aegis escucha.
REGLA_QUIC = f"{PREFIJO}sin QUIC hacia servicios de IA"

MAX_IPS_POR_REGLA = 200


@dataclass(frozen=True)
class Step:
    description: str
    detail: str


def _lista_de_ips(ips) -> str:
    return ",".join(sorted(set(ips))[:MAX_IPS_POR_REGLA])


def _nombre_para(programa: str) -> str:
    base = programa.replace("\\", "/").rsplit("/", 1)[-1]
    return f"{PREFIJO}sin ruta directa para {base}"


def plan(programas, ips) -> list[Step]:
    """Lo que se va a hacer, por escrito y antes de tocar el firewall.

    Vale mas aca que en el instalador: esto necesita administrador y toca una
    configuracion del sistema que el usuario no escribio.
    """

    pasos = [
        Step(
            "Bloquear QUIC hacia los servicios de IA",
            f"UDP 443 hacia {len(set(ips))} direcciones. Obliga a volver a TCP, "
            "que es por donde escucha Aegis.",
        )
    ]
    pasos.extend(
        Step(
            f"Quitarle la ruta directa a {programa.replace(chr(92), '/').rsplit('/', 1)[-1]}",
            "TCP 443 hacia las mismas direcciones, solo para ese programa",
        )
        for programa in programas
    )
    pasos.append(
        Step(
            "Todo queda revertible",
            f"Las reglas van al grupo {GRUPO}; revertir() las borra todas.",
        )
    )
    return pasos


def _netsh(argumentos: list[str]) -> tuple[bool, str]:
    try:
        resultado = subprocess.run(
            ["netsh", "advfirewall", "firewall", *argumentos],
            capture_output=True,
            text=True,
            errors="replace",
        )
        salida = (resultado.stdout or "") + (resultado.stderr or "")
        ok = resultado.returncode == 0
    except OSError as error:
        ok, salida = False, str(error)
    return ok, salida


def bloquear_quic(ips) -> tuple[bool, str]:
    return _netsh(
        [
            "add",
            "rule",
            f"name={REGLA_QUIC}",
            f"group={GRUPO}",
            "dir=out",
            "action=block",
            "protocol=UDP",
            "remoteport=443",
            f"remoteip={_lista_de_ips(ips)}",
            "enable=yes",
        ]
    )


def bloquear_programa(programa: str, ips) -> tuple[bool, str]:
    """Le saca la ruta directa a un programa, no a la maquina entera."""

    return _netsh(
        [
            "add",
            "rule",
            f"name={_nombre_para(programa)}",
            f"group={GRUPO}",
            "dir=out",
            "action=block",
            "protocol=TCP",
            "remoteport=443",
            f"remoteip={_lista_de_ips(ips)}",
            f"program={programa}",
            "enable=yes",
        ]
    )


def revertir() -> tuple[bool, str]:
    """Borra todo lo que puso Aegis, de una sola vez y por grupo."""

    return _netsh(["delete", "rule", f"group={GRUPO}"])


def reglas_puestas() -> list[str]:
    ok, salida = _netsh(["show", "rule", "name=all", f"group={GRUPO}"])
    nombres = []
    if ok:
        for linea in salida.splitlines():
            if linea.strip().lower().startswith(("rule name:", "nombre de regla:")):
                nombre = linea.split(":", 1)[1].strip()
                if nombre.startswith(PREFIJO):
                    nombres.append(nombre)
    return nombres
