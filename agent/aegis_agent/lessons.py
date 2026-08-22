from __future__ import annotations

# Lecciones locales de respaldo. La version buena la genera el backend con un LLM
# a partir del evento redactado (ADR 0003), pero el bloqueo no puede esperar a la
# red: si el backend no responde, el empleado igual tiene que entender que paso.

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


def lesson_for(rule_id: str) -> dict[str, str]:
    return _BY_RULE.get(rule_id, _DEFAULT)
