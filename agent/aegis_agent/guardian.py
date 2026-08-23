"""El proceso que garantiza que Aegis nunca te deje sin internet.

## El estado que existe para evitar

    ProxyEnable = 1, ProxyServer = 127.0.0.1:8899   y nadie escuchando ahi

Ahi el navegador manda todo a un puerto muerto y la persona pierde la red. Es el
UNICO estado en el que Aegis deja el equipo peor que si no estuviera instalado, y
paso de verdad: el proxy se murio a mitad de sesion y quien lo tenia instalado se
quedo sin internet sin ninguna pista de por que.

## Por que un proceso APARTE y no un hilo del servicio

Porque el caso que hay que cubrir es justamente que el servicio muera. Un hilo
adentro del proxy se muere con el proxy, y la limpieza en el `finally` no corre
cuando alguien manda un kill duro o cuando se corta la luz. El guardian es un
proceso separado: si matan el proxy, el guardian sigue vivo y apaga el setting.

Si matan a los dos, queda la ultima red: el reconciliador que corre en cada
invocacion del CLI y en el arranque de sesion.

## Y por que apaga en vez de reintentar

Podria intentar levantar el proxy de nuevo. No lo hace, y es deliberado: si el
proxy se murio hay una razon, y reintentar en un bucle puede dejar a la persona
alternando entre con y sin internet, que es peor que quedarse sin proteccion. La
regla es que la RED gana. Aegis se puede volver a levantar a mano; una tarde de
trabajo perdida no se recupera.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time

# Cada cuanto se mira el puerto, y cuantas fallas seguidas hacen falta para
# actuar. Varias y no una: un reinicio normal del servicio tarda un momento en
# volver a atarse al puerto, y apagar el proxy por eso seria una falsa alarma que
# desprotege a la persona sin motivo.
INTERVALO = 2.0
FALLAS_PARA_ACTUAR = 5


def _escucha(puerto: int) -> bool:
    with socket.socket() as sonda:
        sonda.settimeout(0.5)
        return sonda.connect_ex(("127.0.0.1", puerto)) == 0


def apagar_el_proxy() -> bool:
    """Saca a Aegis del camino del navegador. Es la unica cosa que hace.

    No toca la CA ni las variables de entorno: la CA no molesta a nadie y quitarla
    abre un dialogo de Windows, que es lo ultimo que quiere ver alguien que en ese
    momento no tiene internet.
    """

    try:
        from .install import windows

        windows.write_proxy_settings(False)
        return True
    except Exception:
        return False


def hay_que_actuar(puerto: int) -> bool:
    """El navegador apunta a Aegis y Aegis no esta.

    Las DOS condiciones. Sin la primera, el guardian apagaria un proxy que la
    persona configuro a mano hacia otra cosa.
    """

    try:
        from .install import windows

        estado = windows.read_proxy_settings()
        return bool(estado["enabled"]) and estado["server"] == f"127.0.0.1:{puerto}"
    except Exception:
        return False


def vigilar(puerto: int) -> int:
    """Mira el puerto para siempre. Apaga el proxy si el servicio no vuelve."""

    fallas = 0
    while True:
        if _escucha(puerto):
            fallas = 0
        else:
            fallas += 1
            if fallas >= FALLAS_PARA_ACTUAR and hay_que_actuar(puerto):
                apagar_el_proxy()
                # Se sale despues de actuar: el trabajo del guardian termino y
                # dejar un proceso vigilando un proxy que ya esta apagado solo
                # gasta. El proximo arranque del servicio levanta uno nuevo.
                return 0
        time.sleep(INTERVALO)


def lanzar(puerto: int) -> subprocess.Popen | None:
    """Arranca un guardian desprendido de quien lo llama.

    Desprendido a proposito: tiene que sobrevivir a la muerte del servicio, que es
    exactamente el caso que vino a cubrir.
    """

    from . import entorno

    comando = entorno.ejecutable_del_agente() + ["guardian"]
    banderas = 0
    if os.name == "nt":
        banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    try:
        return subprocess.Popen(
            comando,
            env={**os.environ, "AEGIS_PORT": str(puerto)},
            creationflags=banderas,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        return None


def reconciliar(puerto: int) -> str:
    """La ultima red: arregla el estado malo si ya ocurrio.

    Corre en cada invocacion del CLI y al iniciar sesion, o sea que cubre el caso
    en que mataron al servicio Y al guardian, o en que la maquina se apago de
    golpe con el proxy prendido.

    Devuelve lo que hizo, para poder decirlo. Un arreglo silencioso deja a la
    persona sin entender por que Aegis dejo de estar activo.
    """

    if _escucha(puerto):
        return ""
    if not hay_que_actuar(puerto):
        return ""
    if apagar_el_proxy():
        return (
            "Aegis no estaba corriendo y el navegador seguia apuntandole: se "
            "desactivo el proxy para que no te quedes sin internet."
        )
    return (
        "ATENCION: el navegador apunta a Aegis, Aegis no esta corriendo, y no se "
        "pudo desactivar el proxy. Corre `aegis desinstalar`."
    )


def main() -> int:
    from . import entorno

    return vigilar(entorno.puerto())


if __name__ == "__main__":
    raise SystemExit(main())
