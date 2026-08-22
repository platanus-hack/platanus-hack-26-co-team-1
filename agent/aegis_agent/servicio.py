"""El proxy corriendo en proceso, sin mitmdump.exe y sin un script en disco.

Es la pieza que hace empaquetable al agente. `mitmdump -s aegis_mitm.py` necesita
dos cosas que adentro de un ejecutable no existen: el ejecutable de mitmproxy y un
archivo de script en una ruta. Con `DumpMaster` el addon se agrega en memoria y no
hace falta ninguna de las dos.

`aegis_mitm.py` se queda igual y sigue sirviendo: es como se levanta el proxy en
desarrollo y como lo levantan los tests de punta a punta. Este modulo no lo
reemplaza, le agrega el camino que un paquete puede usar.
"""

from __future__ import annotations

import asyncio
import signal
import sys


def _opciones(puerto: int, host: str):
    from mitmproxy import options

    return options.Options(listen_host=host, listen_port=puerto)


async def _correr(puerto: int, host: str, silencioso: bool) -> None:
    from mitmproxy.tools.dump import DumpMaster

    from .proxy.addon import Aegis

    maestro = DumpMaster(
        _opciones(puerto, host),
        with_termlog=not silencioso,
        # El volcado de flujos se apaga siempre. Aegis no es una herramienta de
        # inspeccion de trafico: escribir cada request a la consola seria contar
        # por la salida estandar justo lo que el ADR 0003 promete que no sale del
        # equipo.
        with_dumper=False,
    )
    maestro.addons.add(Aegis())

    # Ctrl+C y el cierre de sesion de Windows tienen que apagar el proxy de forma
    # ordenada: si el proceso muere sin desarmarse, el navegador se queda apuntando
    # a un puerto que no escucha y la persona pierde internet. Eso es peor que no
    # tener Aegis, y es exactamente el recuerdo que deja desinstalado el producto.
    bucle = asyncio.get_running_loop()
    for senal in (signal.SIGINT, signal.SIGTERM):
        try:
            bucle.add_signal_handler(senal, maestro.shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            # Windows no implementa add_signal_handler para todas las senales.
            # No es fatal: el shutdown por KeyboardInterrupt sigue funcionando.
            pass

    try:
        await maestro.run()
    except KeyboardInterrupt:
        maestro.shutdown()


def correr(puerto: int, host: str = "127.0.0.1", silencioso: bool = True) -> int:
    """Levanta el proxy y no vuelve hasta que se lo apague.

    El host por defecto es loopback y no todas las interfaces: un proxy de
    intercepcion escuchando en 0.0.0.0 es un proxy abierto en la red de la
    oficina, y cualquiera podria mandarle su trafico para que se lo descifren.
    """

    try:
        asyncio.run(_correr(puerto, host, silencioso))
        codigo = 0
    except KeyboardInterrupt:
        codigo = 0
    except OSError as error:
        # Lo mas comun: el puerto ya esta ocupado porque el agente ya esta
        # corriendo. Decirlo en una linea vale mas que un traceback.
        print(f"Aegis no pudo escuchar en el puerto {puerto}: {error}", file=sys.stderr)
        codigo = 1
    return codigo
