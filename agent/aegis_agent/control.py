"""Prender y apagar la proteccion, sin desinstalar nada.

## Por que existe

Hasta aca las unicas dos posiciones eran "instalado" y "desinstalado", y
desinstalar borra la CA del almacen de Windows, saca las variables de entorno y
quita el arranque automatico. Para dejar de interceptar un rato -- probar si una
app se rompe por culpa de Aegis, comparar el trafico con y sin proxy, mostrarle
a alguien el antes y el despues -- eso es demoler la casa para apagar la luz. Y
volver cuesta otro dialogo de Windows pidiendo confiar una CA raiz.

Lo que se prende y se apaga aca es **el ruteo**, que es la unica parte reversible
en un segundo: el navegador apunta al proxy o no. La CA, las variables y el
arranque se quedan como estan, porque no interceptan nada por si solas.

## El invariante que gobierna todo este archivo

**Nunca dejar el navegador apuntando a un puerto donde no hay nadie.** Es el
peor estado que este producto sabe producir -- la persona se queda sin internet
y sin ninguna pista de por que -- y ya ocurrio una vez (ver cli.py). Por eso
`prender` levanta el servicio y COMPRUEBA que escuche antes de rutear, y por eso
`apagar` desrutea primero y despues, recien despues, se plantea parar el
proceso. En los dos sentidos, el orden es el arreglo.

Las dos operaciones son idempotentes: prender lo prendido y apagar lo apagado
devuelven exito sin tocar nada. Un interruptor en una pantalla se aprieta dos
veces sin querer todo el tiempo.
"""

from __future__ import annotations

from . import entorno

# Que significa cada estado, en una palabra, para que el panel y el CLI no
# inventen dos vocabularios distintos para lo mismo.
PROTEGIENDO = "protegiendo"
APAGADO = "apagado"
ROTO = "roto"
SIN_INSTALAR = "sin_instalar"


def estado(puerto: int | None = None) -> dict:
    """Que esta pasando ahora, en la forma que muestran el panel y el CLI.

    `situacion` es el resumen de una palabra y es lo unico que una persona
    necesita leer; el resto son las piezas, para poder decir POR QUE.

    `roto` es el estado peligroso y merece nombre propio: el navegador apunta a
    Aegis y Aegis no esta escuchando. Quien esta ahi no tiene internet.
    """

    from .install import windows

    puerto = entorno.puerto() if puerto is None else puerto
    crudo = windows.status(puerto)

    escuchando = bool(crudo["escuchando"])
    ruteado = bool(crudo["proxy_activo"]) and bool(crudo["apunta_a_aegis"])
    instalado = bool(crudo["ca_generada"])

    if ruteado and escuchando:
        situacion = PROTEGIENDO
    else:
        if ruteado and not escuchando:
            situacion = ROTO
        else:
            situacion = APAGADO if instalado else SIN_INSTALAR

    return {
        "situacion": situacion,
        "puerto": puerto,
        "escuchando": escuchando,
        "ruteado": ruteado,
        "instalado": instalado,
        "ca_confiada": bool(crudo["ca_confiada"]),
        "arranca_solo": bool(crudo["arranca_solo"]),
    }


def prender(puerto: int | None = None) -> tuple[bool, str]:
    """Vuelve a interceptar. Levanta el servicio si hace falta y despues rutea.

    El orden no es negociable y es el mismo que usa `aegis instalar`: primero
    que haya alguien escuchando, comprobarlo, y RECIEN ahi mandarle el trafico
    del navegador. Al reves existe un instante -- o para siempre, si arrancar
    falla -- en el que la persona no tiene internet.
    """

    from .install import windows

    puerto = entorno.puerto() if puerto is None else puerto
    actual = estado(puerto)

    if actual["situacion"] == PROTEGIENDO:
        return True, "Aegis ya estaba protegiendo este equipo."

    if not actual["instalado"]:
        return False, (
            "Aegis no esta instalado en este equipo. Corre `aegis instalar` una "
            "vez y despues este interruptor alcanza para todo lo demas."
        )

    if not actual["escuchando"]:
        from .cli import _arrancar_en_segundo_plano

        if not _arrancar_en_segundo_plano(puerto):
            return False, (
                f"No se pudo levantar Aegis en el puerto {puerto}, asi que NO se "
                "toco el proxy. Preferimos dejarte sin proteccion antes que sin "
                "internet."
            )

    return windows.enrutar(puerto)


def apagar(puerto: int | None = None) -> tuple[bool, str]:
    """Deja de interceptar. No desinstala nada.

    Se desrutea y se deja el proceso vivo a proposito: parar el proxy no aporta
    nada -- sin ruteo no le llega trafico -- y mantenerlo arriba hace que volver
    a prender sea instantaneo, que es justo lo que se quiere cuando alguien esta
    probando algo y va a prender y apagar diez veces.

    La CA, las variables de entorno y el arranque automatico tampoco se tocan:
    ninguna intercepta nada por si sola, y devolverlas cuesta un dialogo de
    Windows. Para sacarlas de verdad esta `aegis desinstalar`.
    """

    from .install import windows

    puerto = entorno.puerto() if puerto is None else puerto
    if not estado(puerto)["ruteado"]:
        return True, "Aegis ya estaba apagado: el navegador no pasa por el proxy."

    windows.write_proxy_settings(False)
    return True, (
        "Aegis apagado. El trafico vuelve a salir directo y el equipo queda sin "
        "proteccion. La instalacion sigue en su lugar: prender de nuevo es "
        "instantaneo."
    )


def alternar(puerto: int | None = None) -> tuple[bool, str]:
    """El interruptor de una sola pantalla: si esta prendido apaga, si no prende."""

    puerto = entorno.puerto() if puerto is None else puerto
    return apagar(puerto) if estado(puerto)["ruteado"] else prender(puerto)
