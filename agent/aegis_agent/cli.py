"""Un solo punto de entrada, que es lo que se empaqueta como Aegis.exe.

    aegis instalar      CA + proxy + variables + arranque automatico, y arranca
    aegis servicio      corre el proxy (es lo que ejecuta el arranque automatico)
    aegis estado        que esta configurado y si esta protegiendo AHORA
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
    from .install import windows

    for hecho in windows.install(puerto):
        print(f"  {hecho}")

    # Arrancar despues de configurar, no antes: si el proxy levanta primero y la
    # configuracion falla, queda un proceso escuchando que nadie pidio.
    if windows.arranque_registrado() and not windows.puerto_escuchando(puerto):
        print("\n  Levantando Aegis...")
        if _arrancar_en_segundo_plano(puerto):
            print(f"  Aegis esta protegiendo este equipo (puerto {puerto})")
        else:
            print("  No se pudo levantar. Corre `aegis servicio` en otra ventana.")
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
    from . import servicio

    return servicio.correr(puerto)


def _demo(puerto: int) -> int:
    from demo import run

    return run.main() or 0


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
    "verificar": "_verificar",
    "desinstalar": "_desinstalar",
    "uninstall": "_desinstalar",
    "plan": "_plan",
    "demo": "_demo",
}


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    accion = argumentos[0].lower() if argumentos else "estado"

    if accion in ("-h", "--help", "help", "ayuda"):
        print(AYUDA)
        codigo = 0
    elif accion in ACCIONES:
        funcion = getattr(sys.modules[__name__], ACCIONES[accion])
        codigo = funcion(entorno.puerto())
    else:
        print(f"No conozco la accion '{accion}'.\n")
        print(AYUDA)
        codigo = 2
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
