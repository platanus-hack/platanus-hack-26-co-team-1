"""Lo que ya se subio y todavia no se leyo.

## Por que existe

El OCR estaba apagado por defecto y no por gusto: cuesta entre 1,7 y 9 segundos
(las mediciones estan en `detect/ocr.py`), o sea entre dos y trece veces el
presupuesto COMPLETO de T2. Pagarlo en el camino critico es frenar a la persona
en el momento en que aprieta enviar, asi que la empresa tenia que elegir entre
ver las capturas de pantalla o no molestar a nadie. Es una eleccion falsa, y
esta es la pieza que la saca.

## La ventana que lo hace posible

Subir el archivo y pedirle al modelo que lo lea son DOS requests distintos --se
descubrio armando `subidas.py`-- y entre los dos hay una ventana real: la
persona tiene que escribir el mensaje y apretar enviar. Ahi vive el OCR.

Y lo importante es que frenar el SEGUNDO request sigue siendo suficiente: **el
archivo en el blob todavia no es una fuga**. Nadie lo mira, no esta en ningun
historial, no lo leyo ningun modelo. La fuga es el turno que le pide al modelo
que lo lea, y ese turno es el que se corta. La proteccion es la misma; lo que
cambia es donde se paga.

## Lo que NO hace, a proposito

**No se pasa de listo con la espera.** Si el turno llega antes de que la lectura
termine --alguien que sube y aprieta enviar de inmediato-- se espera, con
presupuesto. No dejarlo pasar seria mentir sobre la proteccion; esperar sin
limite seria volver al problema original. En el caso comun la lectura ya termino
y la espera es cero, y en el peor se paga una parte del OCR en vez de todo.

**No adivina de quien es el archivo.** La clave es el host de IA que
`subidas.py` ya devuelve mirando el `Origin` del propio request. Sin ese dato no
hay pendiente que registrar, que es el mismo limite que ya tiene la deteccion de
subidas y se arregla en el mismo lugar (la correlacion por proceso del ADR 0004).

**No decide.** Devuelve hallazgos; que hacer con ellos lo sigue decidiendo
`policy.decidir_sobre`, igual que con cualquier otro hallazgo.
"""

from __future__ import annotations

import os
import threading
import time

from .detect import ocr
from .detect.imagenes import extraer as extraer_imagenes

# Cuanto se espera, como maximo, a que termine una lectura que todavia corre
# cuando llega el turno. Es el techo del peor caso, no lo que se paga siempre:
# si la persona tardo en escribir --que es lo normal-- la lectura ya termino y
# esto no espera nada.
ESPERA_MAXIMA_MS = int(os.environ.get("AEGIS_OCR_ESPERA_MS", "3000"))

# Cuanto vive un pendiente sin que nadie lo cobre. Alguien que adjunta un
# archivo, se arrepiente y lo saca antes de enviar no tiene que arrastrar ese
# hallazgo al resto de la conversacion.
VIDA_MS = int(os.environ.get("AEGIS_OCR_VIDA_MS", "180000"))

# Cuantas lecturas se pueden estar haciendo a la vez. Cada una ocupa un hilo y
# CPU; sin techo, arrastrar veinte imagenes de golpe deja el equipo de rodillas
# justo cuando la persona esta trabajando.
MAX_EN_VUELO = int(os.environ.get("AEGIS_OCR_EN_VUELO", "2"))


class _Lectura:
    """Una imagen que se esta leyendo, y lo que se encontro cuando termine."""

    __slots__ = ("listo", "hallazgos", "incompleto", "nacida")

    def __init__(self) -> None:
        self.listo = threading.Event()
        self.hallazgos: list = []
        self.incompleto = False
        self.nacida = time.time()


_pendientes: dict[str, list[_Lectura]] = {}
_candado = threading.Lock()
_en_vuelo = threading.Semaphore(MAX_EN_VUELO)


def _vencida(lectura: _Lectura, ahora: float) -> bool:
    return (ahora - lectura.nacida) * 1000 > VIDA_MS


def _limpiar(ahora: float) -> None:
    """Saca lo que ya nadie va a cobrar. Se llama con el candado tomado."""

    for destino in list(_pendientes):
        vivas = [x for x in _pendientes[destino] if not _vencida(x, ahora)]
        if vivas:
            _pendientes[destino] = vivas
        else:
            del _pendientes[destino]


def registrar(destino: str, payload: bytes | None, texto: str, escanear) -> int:
    """Arranca la lectura de las imagenes de una subida. Devuelve cuantas.

    `escanear` recibe el texto que salio del OCR y devuelve los hallazgos. Se
    pasa como parametro --igual que `es_ia` en `subidas.py`-- para que este
    modulo no dependa de la politica: quien llama ya la tiene en la mano.

    No lanza nunca. Una subida que no se puede leer tiene que seguir siendo una
    subida que pasa, no un error en la cara de la persona.
    """

    imagenes: list[bytes] = []
    if destino and ocr.habilitado():
        try:
            imagenes = extraer_imagenes(payload, texto)
        except Exception:
            imagenes = []

    for imagen in imagenes:
        lectura = _Lectura()
        with _candado:
            _limpiar(time.time())
            _pendientes.setdefault(destino, []).append(lectura)
        hilo = threading.Thread(
            target=_leer, args=(imagen, lectura, escanear), daemon=True
        )
        hilo.start()

    return len(imagenes)


def _leer(imagen: bytes, lectura: _Lectura, escanear) -> None:
    """El trabajo caro, lejos del camino critico.

    El semaforo se toma ACA y no antes de arrancar el hilo: si se tomara antes,
    registrar una subida con cinco imagenes bloquearia el request que la trajo,
    que es justo lo que este modulo existe para no hacer.
    """

    with _en_vuelo:
        try:
            textos, incompleto = ocr.vistas([imagen])
            lectura.incompleto = incompleto
            unido = "\n".join(t for t in textos if t)
            if unido.strip():
                lectura.hallazgos = list(escanear(unido) or [])
        except Exception:
            # Que la lectura falle no puede dejar el turno esperando para
            # siempre: se marca lista sin hallazgos y el envio sigue su camino.
            lectura.hallazgos = []
        finally:
            lectura.listo.set()


def cobrar(destino: str, espera_ms: int | None = None) -> tuple[list, bool]:
    """Lo que encontraron las lecturas de lo que se subio antes a este destino.

    Devuelve `(hallazgos, incompleto)` y **consume** los pendientes: si no, un
    solo hallazgo bloquearia todos los turnos siguientes de la conversacion y la
    persona no tendria forma de seguir aunque sacara el adjunto.
    """

    ahora = time.time()
    with _candado:
        _limpiar(ahora)
        lecturas = _pendientes.pop(destino, [])

    limite = ahora + (ESPERA_MAXIMA_MS if espera_ms is None else espera_ms) / 1000
    hallazgos: list = []
    incompleto = False
    for lectura in lecturas:
        restante = limite - time.time()
        if restante > 0:
            lectura.listo.wait(restante)
        if lectura.listo.is_set():
            hallazgos.extend(lectura.hallazgos)
            incompleto = incompleto or lectura.incompleto
        else:
            # Se acabo el presupuesto y esta lectura sigue corriendo. El envio
            # pasa, pero el escaneo NO fue completo y quien decide tiene que
            # saberlo: es la misma senal que da un payload truncado.
            incompleto = True
    return hallazgos, incompleto


def hay_pendientes(destino: str) -> bool:
    """Si queda algo por cobrar para este destino. Para los tests y el estado."""

    with _candado:
        _limpiar(time.time())
        return bool(_pendientes.get(destino))


def olvidar_todo() -> None:
    """Vacia los pendientes. Los tests no pueden heredar los del anterior."""

    with _candado:
        _pendientes.clear()
