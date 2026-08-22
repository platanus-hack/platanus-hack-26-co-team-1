from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

# Lecciones locales de respaldo. La version buena la genera el backend con un LLM
# a partir del evento redactado (ADR 0003), pero el bloqueo no puede esperar a la
# red: si el backend no responde, el empleado igual tiene que entender que paso.
#
# El orden es el mismo que usa domains.py y por la misma razon: se lee del cache
# en disco, siempre, y la red solo actualiza ese cache en segundo plano. La
# consecuencia hay que decirla en voz alta: a la PRIMERA persona a la que se le
# corta una regla le toca la leccion escrita a mano, y a partir de ahi la
# generada. Es el precio de que la red nunca este en el camino de la proteccion,
# y es el precio correcto.

_DEFAULT = {
    "title": "Esta informacion no deberia salir de la empresa",
    "why": (
        "Lo que ibas a enviar identifica a la empresa o da acceso a sus sistemas. "
        "Una vez que sale, no hay forma de traerlo de vuelta."
    ),
    "what_to_do": (
        "Quitalo del texto y volve a intentar. Si necesitas que la IA trabaje sobre "
        "eso, reemplazalo por un valor de ejemplo."
    ),
}

_BY_RULE: dict[str, dict[str, str]] = {
    "aws_access_key_id": {
        "title": "Las credenciales de AWS abren la infraestructura completa",
        "why": (
            "Una llave de acceso de AWS permite crear, leer y borrar recursos en la "
            "nube de la empresa. Compartirla equivale a entregar la llave del "
            "servidor, y quien la reciba no necesita nada mas para usarla."
        ),
        "what_to_do": (
            "Pedile ayuda a la IA con el codigo, no con la credencial: reemplazala "
            "por AKIAEXAMPLE. Si la llave ya se compartio antes, hay que rotarla hoy "
            "desde la consola de AWS."
        ),
    },
    "anthropic_api_key": {
        "title": "Una API key es tuya, aunque el servicio sea aprobado",
        "why": (
            "La API key factura a nombre de la empresa y no caduca sola. Pegarla en "
            "un chat la deja registrada en un historial que no controlas."
        ),
        "what_to_do": (
            "Para que la IA revise codigo que usa la key, dejala como variable de "
            "entorno en el ejemplo. Nunca hace falta el valor real para que entienda."
        ),
    },
    "openai_api_key": {
        "title": "Una API key es tuya, aunque el servicio sea aprobado",
        "why": (
            "La API key factura a nombre de la empresa y no caduca sola. Pegarla en "
            "un chat la deja registrada en un historial que no controlas."
        ),
        "what_to_do": (
            "Reemplazala por un marcador tipo OPENAI_API_KEY antes de pegar el codigo."
        ),
    },
    "db_connection_string": {
        "title": "La cadena de conexion lleva usuario y contrasena adentro",
        "why": (
            "Se ve como una URL, pero incluye las credenciales de la base de datos de "
            "produccion. Con eso alcanza para leer todos los datos de los clientes."
        ),
        "what_to_do": (
            "Mandale a la IA solo el esquema o la consulta. Para la conexion usa "
            "postgres://usuario:clave@host/basedatos como ejemplo."
        ),
    },
    "private_key_block": {
        "title": "Una llave privada no se comparte con nadie, nunca",
        "why": (
            "Es la mitad secreta de un par de llaves: sirve para firmar y descifrar en "
            "nombre de la empresa. No existe un caso donde tenga que salir del equipo."
        ),
        "what_to_do": (
            "Si necesitas ayuda con la configuracion, compartí solo la parte publica "
            "o el mensaje de error, sin el bloque de la llave."
        ),
    },
    "archivo_critico": {
        "title": "Ese archivo no esta hecho para salir del equipo",
        "why": (
            "Un .env, una llave, un volcado de base de datos o un respaldo "
            "contienen la configuracion y los datos con los que funciona la "
            "empresa. No importa que lo que se vea adentro parezca inofensivo: "
            "el archivo completo es el problema."
        ),
        "what_to_do": (
            "Si necesitas ayuda con ese archivo, pega solo la parte concreta que "
            "no funciona, con los valores reemplazados por ejemplos."
        ),
    },
    "archivo_critico_por_firma": {
        "title": "Ese archivo es una base de datos, aunque no lo parezca",
        "why": (
            "El nombre decia otra cosa, pero por dentro es un volcado o una base "
            "de datos completa. Ahi viven los datos de todos los clientes, no una "
            "muestra."
        ),
        "what_to_do": (
            "Trabaja sobre el esquema o sobre unas pocas filas de ejemplo "
            "inventadas, nunca sobre el archivo real."
        ),
    },
    "credit_card": {
        "title": "Los datos de tarjetas tienen reglas propias",
        "why": (
            "Los numeros de tarjeta estan cubiertos por normas de proteccion de datos. "
            "Enviarlos a un tercero puede ser una falta de cumplimiento, ademas del "
            "riesgo directo de fraude."
        ),
        "what_to_do": (
            "Trabaja con los ultimos cuatro digitos o con un identificador interno de "
            "la transaccion."
        ),
    },
    "credencial_en_espanol": {
        "title": "Una contrasena escrita en una frase sigue siendo una contrasena",
        "why": (
            "No hace falta que este en un archivo de configuracion para que sirva: "
            "quien lea esa frase entra igual. Y una vez que sale del equipo ya no "
            "se puede saber donde quedo guardada, ni por cuanto tiempo, ni quien la "
            "va a leer despues."
        ),
        "what_to_do": (
            "Contale a la IA el problema sin la clave: 'no puedo entrar al panel con "
            "el usuario de soporte' alcanza para que te ayude. Si la clave ya salio "
            "antes, cambiala hoy: es lo unico que la vuelve inservible."
        ),
    },
    "credencial_en_espanol_sin_verbo": {
        "title": "Una contrasena escrita en una frase sigue siendo una contrasena",
        "why": (
            "No hace falta que este en un archivo de configuracion para que sirva: "
            "quien lea esa frase entra igual. Y una vez que sale del equipo ya no "
            "se puede saber donde quedo guardada, ni por cuanto tiempo, ni quien la "
            "va a leer despues."
        ),
        "what_to_do": (
            "Contale a la IA el problema sin la clave: 'no puedo entrar al panel con "
            "el usuario de soporte' alcanza para que te ayude. Si la clave ya salio "
            "antes, cambiala hoy: es lo unico que la vuelve inservible."
        ),
    },
}


RUTA_CACHE = Path(
    os.environ.get("AEGIS_LESSONS_CACHE", "aegis-lessons-cache.json")
)

TIMEOUT = 20

_lock = threading.Lock()
_pedidas: set[str] = set()


def _cache() -> dict[str, dict[str, str]]:
    """Lo que ya escribio el modelo, de disco. Un cache ilegible no es un error."""

    try:
        datos = json.loads(RUTA_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    return datos if isinstance(datos, dict) else {}


def _guardar(rule_id: str, leccion: dict) -> None:
    datos = _cache()
    datos[rule_id] = {
        "title": leccion.get("title", ""),
        "why": leccion.get("why", ""),
        "what_to_do": leccion.get("what_to_do", ""),
    }
    try:
        RUTA_CACHE.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # Sin disco donde escribir se pierde el cache, no la leccion: la proxima
        # vez se vuelve a pedir y mientras tanto queda la escrita a mano.
        pass


def lesson_for(rule_id: str) -> dict[str, str]:
    """La leccion para una regla: la generada si ya existe, si no la de siempre."""

    generada = _cache().get(rule_id)
    completa = isinstance(generada, dict) and all(
        generada.get(clave) for clave in ("title", "why", "what_to_do")
    )
    return generada if completa else _BY_RULE.get(rule_id, _DEFAULT)


def pedir_en_segundo_plano(evento: dict, url_base: str, repeticiones: int = 0) -> None:
    """Le pide al backend la leccion de esta regla, para la proxima vez.

    No devuelve nada y nadie la espera: el bloqueo ya se resolvio con lo que
    habia en disco. Se pide una sola vez por regla y por proceso, porque el
    backend ya cachea y no tiene sentido pagar dos veces la misma llamada.
    """

    rule_id = ((evento.get("detection") or {}).get("rule_id")) or ""
    if not rule_id:
        return

    with _lock:
        if rule_id in _pedidas or rule_id in _cache():
            return
        _pedidas.add(rule_id)

    def _tarea() -> None:
        try:
            cuerpo = json.dumps(
                {"event": evento, "repeticiones": repeticiones}
            ).encode()
            peticion = urllib.request.Request(
                f"{url_base.rstrip('/')}/v1/lessons",
                data=cuerpo,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
                leccion = json.loads(respuesta.read())
            if leccion.get("generada_por") in ("modelo", "cache"):
                _guardar(rule_id, leccion)
        except (urllib.error.URLError, OSError, ValueError, TypeError):
            # Backend caido, sin red o respuesta rara: queda la leccion escrita a
            # mano y se puede volver a pedir en el proximo arranque.
            with _lock:
                _pedidas.discard(rule_id)

    threading.Thread(target=_tarea, daemon=True).start()
