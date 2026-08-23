"""Cuantas veces seguidas se puede probar una credencial, y desde donde.

## El agujero que cierra

`/v1/login`, `/v1/enrolar` y `/v1/registro` son los tres endpoints que no piden
sesion --no pueden pedirla, son los que la dan-- y aceptaban intentos
ilimitados. Los tres ya hacian bien la parte dificil: un solo motivo de rechazo,
sin filtrar si el usuario existe. Lo que faltaba era el contador, y sin contador
esa discrecion no sirve de mucho: quien puede probar sin limite no necesita que
el servidor le diga nada, se entera por cual funciona.

En login es adivinar contrasenas a la velocidad de la red. En enrolar es moler
codigos hasta entrar a una empresa. En registro es ocupar nombres de empresa en
masa, que no roba nada pero deja el producto inservible.

## Las decisiones

**Se cuenta por IP y ADEMAS por objetivo.** Contar solo por IP se esquiva con
proxies rotativos, y contar solo por objetivo permite que alguien bloquee la
cuenta de otro a proposito -- que es un ataque de negacion, no de acceso. Las
dos juntas: quien rota IPs choca con el contador del usuario, y quien ataca a un
usuario desde una IP choca con el de la IP. Un usuario legitimo que se equivoca
tres veces no toca ninguno de los dos limites.

**La IP se lee de `X-Forwarded-For` cuando esta.** Detras de Render todos los
pedidos llegan de la misma IP interna, asi que sin esto habria un solo balde
para todo el mundo y el primero que se equivoque deja afuera al resto. La
cabecera se puede falsear cuando no hay un proxy de confianza adelante, y por
eso NO es el unico contador: para eso esta el de objetivo, que no se puede
rotar.

**Un acierto borra la cuenta.** Si no, alguien que se equivoca cuatro veces y
entra bien a la quinta arrastra el castigo el resto de la ventana.

**Todo en memoria y por proceso.** Es una eleccion, no una limitacion: la
alternativa es una tabla mas en Supabase escrita en el camino del login, con su
latencia y su modo de fallar. Lo que se pierde es que el contador se reinicia al
redesplegar, y eso a un atacante le sirve de poco -- son ventanas de minutos.
"""

from __future__ import annotations

import threading
import time

# Cinco intentos por ventana. Quien escribe mal la contrasena la escribe mal dos
# o tres veces, no cinco; quien prueba una lista necesita millones.
LIBRES = 5

# Cinco minutos. Corto a proposito: el objetivo es que probar salga caro, no
# castigar a quien de verdad se olvido.
VENTANA = 300.0

_marcas: dict[str, list[float]] = {}
_candado = threading.Lock()


def _vigentes(clave: str, ahora: float) -> list[float]:
    """Los intentos de `clave` que todavia caen dentro de la ventana."""

    return [t for t in _marcas.get(clave, []) if ahora - t < VENTANA]


def permitido(*claves: str, ahora: float | None = None) -> bool:
    """Si TODAS las claves todavia tienen intentos disponibles.

    Se pasan varias --la IP y el objetivo-- y alcanza con que una este agotada
    para frenar el pedido.
    """

    momento = time.time() if ahora is None else ahora
    with _candado:
        libre = all(len(_vigentes(c, momento)) < LIBRES for c in claves if c)
    return libre


def anotar(*claves: str, ahora: float | None = None) -> None:
    """Suma un intento a cada clave."""

    momento = time.time() if ahora is None else ahora
    with _candado:
        for clave in claves:
            if clave:
                _marcas[clave] = [*_vigentes(clave, momento), momento]


def olvidar(*claves: str) -> None:
    """Borra la cuenta de cada clave. Se llama cuando el intento salio bien."""

    with _candado:
        for clave in claves:
            _marcas.pop(clave, None)


def reiniciar() -> None:
    """Vacia todo. Para los tests, que no pueden heredar el estado del anterior."""

    with _candado:
        _marcas.clear()


def desde_donde(cliente: str, reenviada: str | None) -> str:
    """La IP a la que se le cuentan los intentos.

    `X-Forwarded-For` trae la cadena de proxies y el primero es el cliente
    original. Se toma ese; si no hay cabecera, la direccion del socket.
    """

    primera = (reenviada or "").split(",")[0].strip()
    return primera or (cliente or "")
