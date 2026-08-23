"""Un solo punto de entrada, que es lo que se empaqueta como Aegis.exe.

    aegis instalar      CA + proxy + variables + arranque automatico, y arranca
    aegis panel         abre el panel local: metricas y el interruptor
    aegis prender       vuelve a interceptar (no reinstala nada)
    aegis apagar        deja de interceptar (no desinstala nada)
    aegis estado        que esta configurado y si esta protegiendo AHORA
    aegis servicio      corre el proxy (es lo que ejecuta el arranque automatico)
    aegis verificar     prueba de punta a punta con un secreto de juguete
    aegis desinstalar   revierte todo
    aegis demo          el producto funcionando, sin tocar el sistema

## Por que un CLI nuevo y no los modulos que ya estaban

Porque `python -m aegis_agent.install.windows install` mas `mitmdump -s
aegis_mitm.py` no es un producto: es un flujo de desarrollador. Pide Python, pip,
y saber que hay que correr dos cosas distintas y en que orden.

Y sobre todo: **hasta ahora "instalar" no arrancaba nada.** Configuraba el proxy
del navegador para que apuntara a 127.0.0.1 y ahi no habia nadie escuchando, asi
que la persona quedaba sin internet hasta que alguien corriera el proxy a mano.
Es la falla del peor tipo, porque el usuario no tiene forma de saber que le falto
un paso. Aca instalar arranca, y `estado` distingue "configurado" de
"protegido".
"""

from __future__ import annotations

import os
import sys

from . import entorno

AYUDA = __doc__


def _instalar(puerto: int) -> int:
    """El orden de los pasos ES el arreglo, no un detalle de estilo.

    Antes: configurar el proxy del navegador y despues arrancar. Entre las dos
    cosas --y para siempre, si arrancar fallaba-- el navegador apuntaba a un
    puerto muerto y la persona quedaba SIN INTERNET, sin ninguna pista de por que.

    Ahora: arrancar, CONFIRMAR que escucha, y recien entonces enrutar el trafico.
    Asi el estado peligroso no existe en ningun momento, ni siquiera por un
    instante, ni siquiera si algo falla en el medio.
    """

    from .install import windows

    # 1. La CA y las variables. No redirigen nada, asi que son seguras de hacer
    #    primero: si el proceso muere aca, la red de la persona esta intacta.
    for hecho in windows.install(puerto):
        print(f"  {hecho}")

    # 2. El servicio, y se VERIFICA que escuche. Decirle a alguien que esta
    #    protegido sin comprobarlo es la unica mentira que este producto no se
    #    puede permitir.
    if not windows.puerto_escuchando(puerto):
        print()
        print("  Levantando Aegis...")
        if not _arrancar_en_segundo_plano(puerto):
            print(
                "  NO se pudo levantar Aegis, asi que NO se toco tu proxy.\n"
                "  Tu red esta intacta. Corre `aegis instalar` de nuevo o revisa\n"
                f"  si algo mas esta usando el puerto {puerto}."
            )
            return 1

    # 3. Recien ahora el trafico. enrutar() vuelve a chequear el puerto y la CA:
    #    dos veces, porque es el paso que puede dejar a alguien sin internet.
    enrutado, detalle = windows.enrutar(puerto)
    print(f"  {detalle}")

    # 4. Y el guardian, que apaga el proxy si el servicio se muere despues.
    if enrutado:
        from . import guardian

        if guardian.lanzar(puerto) is not None:
            print("  Guardian activo: si Aegis se cae, te devuelve la red solo")
        else:
            print("  AVISO: no se pudo lanzar el guardian")
        print()
        print(f"  Aegis esta protegiendo este equipo (puerto {puerto})")
    return 0


def _arrancar_en_segundo_plano(puerto: int) -> bool:
    """Lanza el servicio desprendido de esta consola.

    Sin CREATE_NO_WINDOW aparece una consola negra en la cara de la persona cada
    vez que inicia sesion, y eso no dura instalado una semana.
    """

    import subprocess
    import time

    comando = entorno.ejecutable_del_agente() + ["servicio"]
    banderas = 0
    if os.name == "nt":
        banderas = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    try:
        subprocess.Popen(
            comando,
            creationflags=banderas,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        return False

    from .install import windows

    # El proxy tarda un momento en atarse al puerto. Se espera y se COMPRUEBA, en
    # vez de suponer que arranco: decirle a alguien que esta protegido sin haberlo
    # verificado es la unica mentira que este producto no se puede permitir.
    limite = time.time() + 15
    while time.time() < limite:
        if windows.puerto_escuchando(puerto):
            return True
        time.sleep(0.4)
    return False


def _estado(puerto: int) -> int:
    from .install import windows

    estado = windows.status(puerto)
    for clave, valor in estado.items():
        print(f"  {clave}: {valor}")

    # El resumen en una linea, que es lo unico que le importa a una persona que no
    # escribio esto. "Configurado" y "protegido" no son lo mismo y hasta ahora se
    # veian iguales.
    protegido = estado["escuchando"] and estado["apunta_a_aegis"] and estado["ca_confiada"]
    print()
    if protegido:
        print("  Aegis esta protegiendo este equipo.")
    elif estado["apunta_a_aegis"] and not estado["escuchando"]:
        print(
            "  ATENCION: el navegador apunta a Aegis y Aegis no esta corriendo.\n"
            "  Vas a quedarte sin internet. Corre `aegis servicio` o `aegis desinstalar`."
        )
    else:
        print("  Aegis no esta activo en este equipo.")
    return 0 if protegido else 1


def _desinstalar(puerto: int) -> int:
    from .install import windows

    # El orden importa: primero se saca el proxy del navegador y despues se apaga
    # el proceso. Al reves, entre las dos cosas queda una ventana en la que el
    # navegador apunta a un puerto muerto y la persona no tiene internet.
    for hecho in windows.uninstall():
        print(f"  {hecho}")
    print("  Aegis quedo fuera del camino. El proceso se apaga al cerrar sesion.")
    return 0


def _verificar(puerto: int) -> int:
    from .install import windows

    filas = windows.verificar(puerto)
    for camino, cubierto, motivo in filas:
        print(f"  [{'SI ' if cubierto else 'NO '}] {camino}")
        print(f"         {motivo}")
    return 0 if all(cubierto for _, cubierto, _ in filas) else 1


def _plan(puerto: int) -> int:
    from .install import windows

    for paso in windows.plan(puerto):
        print(f"  - {paso.description}\n      {paso.detail}")
    print(f"  - Registrar el arranque automatico\n      {windows.comando_de_arranque(puerto)}")
    return 0


def _servicio(puerto: int) -> int:
    """Corre el proxy, con su guardian al lado.

    El guardian se lanza aca y no solo en `instalar` porque el arranque
    automatico ejecuta esta accion directamente: sin esto, despues de reiniciar
    la maquina el proxy quedaria sin red de contencion.
    """

    from . import guardian, servicio

    if windows_apunta_a_aegis(puerto):
        guardian.lanzar(puerto)
    return servicio.correr(puerto)


def windows_apunta_a_aegis(puerto: int) -> bool:
    """Si no le apunta, no hace falta guardian: no hay nada que devolver."""

    try:
        from .install import windows

        estado = windows.read_proxy_settings()
        return bool(estado["enabled"]) and estado["server"] == f"127.0.0.1:{puerto}"
    except Exception:
        return False


def _guardian(puerto: int) -> int:
    from . import guardian

    return guardian.vigilar(puerto)


def _demo(puerto: int) -> int:
    from demo import run

    return run.main() or 0


def _panel(puerto: int) -> int:
    """Levanta el panel local y abre el navegador ahi.

    Es el comando que convierte a Aegis en algo que se puede mirar sin saber
    ninguno de los otros: muestra que vio el agente y trae el interruptor para
    prenderlo y apagarlo mientras se prueban cosas.
    """

    import secrets
    import threading
    import webbrowser
    from pathlib import Path

    from .events import DEFAULT_QUEUE
    from .panel import server as panel

    puerto_panel = int(os.environ.get("AEGIS_PANEL_PORT", panel.DEFAULT_PORT))
    cola = Path(os.environ.get("AEGIS_QUEUE", str(DEFAULT_QUEUE)))
    token = secrets.token_urlsafe(24)

    try:
        servidor = panel.serve(cola, puerto_panel, token=token)
    except OSError as error:
        print(f"  No se pudo abrir el panel en el puerto {puerto_panel}: {error}")
        print(f"  Si ya hay uno abierto, esta en http://127.0.0.1:{puerto_panel}")
        return 1

    url = f"http://127.0.0.1:{puerto_panel}"
    print(f"  Panel de Aegis en {url}")
    print("  Ctrl+C para cerrarlo. El agente sigue corriendo igual.")

    # Se abre despues de que el servidor ya escucha: al reves el navegador llega
    # primero y muestra un error que no es real.
    threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print(chr(10) + "  Panel cerrado. Aegis no se toco.")
    finally:
        servidor.server_close()
    return 0


def _prender(puerto: int) -> int:
    from . import control

    ok, mensaje = control.prender(puerto)
    print(f"  {mensaje}")
    return 0 if ok else 1


def _apagar(puerto: int) -> int:
    from . import control

    ok, mensaje = control.apagar(puerto)
    print(f"  {mensaje}")
    return 0 if ok else 1



# El mapa guarda NOMBRES y no funciones, y la busqueda es en tiempo de llamada.
#
# La primera version guardaba las funciones directo, y eso tiene una consecuencia
# que no se ve leyendo: un `patch.object(cli, "_desinstalar")` no cambia nada,
# porque el diccionario ya se quedo con la referencia vieja al importar el modulo.
# Un test que creia estar parcheando el desinstalador **corrio el de verdad**:
# apago el proxy del navegador de la maquina, borro las variables de entorno y
# abrio un dialogo de Windows pidiendo borrar una CA raiz del almacen personal.
#
# Con el nombre, parchear el modulo funciona como cualquiera esperaria. Y en un
# proyecto donde una accion escribe en el registro y corre certutil, "se comporta
# como cualquiera esperaria" no es una comodidad: es lo que evita que un test
# desconfigure la maquina de alguien.
ACCIONES: dict[str, str] = {
    "instalar": "_instalar",
    "install": "_instalar",
    "servicio": "_servicio",
    "run": "_servicio",
    "estado": "_estado",
    "status": "_estado",
    "panel": "_panel",
    "prender": "_prender",
    "encender": "_prender",
    "apagar": "_apagar",
    "verificar": "_verificar",
    "desinstalar": "_desinstalar",
    "uninstall": "_desinstalar",
    "plan": "_plan",
    "demo": "_demo",
    "guardian": "_guardian",
}


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    accion = argumentos[0].lower() if argumentos else "estado"

    if accion in ("-h", "--help", "help", "ayuda"):
        print(AYUDA)
        codigo = 0
    elif accion in ACCIONES:
        # La ultima red, antes de cualquier accion: si el navegador apunta a Aegis
        # y Aegis no esta, se apaga el proxy y se DICE. Cubre el caso en que
        # mataron al servicio y al guardian, o en que la maquina se apago de golpe.
        #
        # Se hace en cada invocacion y no solo en `estado` porque la persona que
        # se quedo sin internet va a escribir cualquier cosa, no la correcta.
        if accion not in ("servicio", "run", "guardian"):
            from . import guardian as _g

            aviso = _g.reconciliar(entorno.puerto())
            if aviso:
                print(f"  {aviso}")
                print()
        funcion = getattr(sys.modules[__name__], ACCIONES[accion])
        codigo = funcion(entorno.puerto())
    else:
        print(f"No conozco la accion '{accion}'.\n")
        print(AYUDA)
        codigo = 2
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
