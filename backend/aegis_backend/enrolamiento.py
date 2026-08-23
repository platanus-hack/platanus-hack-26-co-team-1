"""El codigo que ata un equipo a una empresa.

## El agujero que cierra

`POST /v1/events` no pedia NADA. Cualquiera con la URL podia mandar un evento
con el `tenant_id` que se le ocurriera y quedaba guardado: inventar incidentes
en el panel de una empresa, atribuirselos a una persona real, o simplemente
llenarlo de ruido hasta que nadie lo mire. En un producto cuyo valor es el
registro, un registro en el que cualquiera puede escribir no vale nada.

Y del otro lado faltaba la mitad simetrica: el instalador nunca configuraba
`AEGIS_EVENTS_URL`, asi que un agente recien instalado protegia el equipo y no
le hablaba a ningun panel. La empresa lo veia vacio y concluia que nadie usa IA.

Las dos cosas se arreglan con la misma pieza: un codigo que el panel genera, la
persona pega una vez al instalar, y que a cambio devuelve a donde reportar y con
que credencial.

## Las decisiones

**El codigo se escribe a mano, asi que se disena para eso.** `AEGIS-4K7M-9PQR`:
sin las letras y numeros que se confunden entre si (0/O, 1/I/L), en mayusculas,
en dos grupos de cuatro. Se compara sin distinguir mayusculas y sin los guiones,
porque la mitad de la gente los va a omitir.

**El codigo NO es la credencial.** Se canjea una vez por un token de equipo
firmado, y es ese token el que viaja en cada evento. Asi el codigo se puede
compartir por chat sin que quien lo lea pueda leer los eventos de nadie, y un
equipo que ya se enrolo no depende de que el codigo siga vivo.

**El tenant sale del TOKEN, nunca del evento.** Es la misma regla que ya gobierna
a las sesiones (ver cuentas.py): si el `tenant_id` del cuerpo decidiera, el
token no serviria de nada -- bastaria con mandar otro numero.

**El token de equipo no vence.** Una sesion de persona vence a las ocho horas
porque hay alguien para volver a entrar; un equipo instalado no tiene a nadie
que lo renueve, y un agente que deja de reportar en silencio es exactamente el
estado que este archivo existe para evitar. Se revoca por codigo, no por tiempo.

**Y revocar por codigo tiene que revocar de verdad.** La primera version de esto
decia justo lo de arriba y no lo cumplia: `revocar` marcaba la fila y solo
frenaba canjes FUTUROS, porque el token emitido no guardaba ninguna referencia
al codigo del que habia salido y `leer_equipo` no tenia contra que compararlo.
Un equipo enrolado quedaba afuera de todo mecanismo de baja, para siempre, y lo
unico que quedaba era rotar la llave del servidor -- que desloguea a todas las
personas de todas las empresas a la vez. Por eso el token lleva `jti`: el codigo
que lo origino. Con eso la baja del codigo alcanza al equipo que ya se enrolo.
"""

from __future__ import annotations

import secrets
import time

from . import cuentas, supabase

TABLA = "aegis_enrolamiento"

# El alfabeto de Crockford: los diez digitos y las letras menos I, L, O y U.
#
# No se inventa uno propio, y eso lo decidio un test. La primera version sacaba
# la S pero dejaba el 5, y esa asimetria es el peor error posible: alguien lee un
# 5, escribe una S, y el codigo "no existe" -- sin ninguna pista de que el
# problema fue un caracter. Crockford saca las letras que se confunden con un
# digito y ADEMAS mapea la confusion al canjear (ver _normalizar), asi que quien
# escribe O en vez de 0 entra igual.
ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

# Lo que alguien teclea cuando leyo mal, y a que corresponde de verdad.
CONFUSIONES = str.maketrans({"O": "0", "I": "1", "L": "1"})
GRUPOS = 2
LARGO_DE_GRUPO = 4
PREFIJO = "AEGIS"

# Cuanto vale un codigo antes de que haya que pedir otro. No es una medida de
# seguridad fuerte -- el codigo solo sirve para ENTRAR, no para leer -- sino una
# forma de que un codigo pegado en un chat de hace meses no siga sirviendo.
VIGENCIA = 30 * 24 * 3600

_memoria: dict[str, dict] = {}


# -- el codigo ---------------------------------------------------------------


def _normalizar(codigo: str) -> str:
    """Sin guiones, sin espacios y en mayusculas.

    La mitad de la gente escribe el codigo sin los guiones y la otra mitad lo
    pega con un espacio adelante. Ninguna de las dos cosas es un codigo
    equivocado.
    """

    limpio = "".join(c for c in (codigo or "").upper() if c.isalnum())
    return limpio.translate(CONFUSIONES)


def _generar_texto() -> str:
    grupos = [
        "".join(secrets.choice(ALFABETO) for _ in range(LARGO_DE_GRUPO))
        for _ in range(GRUPOS)
    ]
    return "-".join([PREFIJO, *grupos])


def crear(tenant: str, ahora: float | None = None) -> dict:
    """Un codigo nuevo para que un equipo se sume a esta empresa."""

    ahora = time.time() if ahora is None else ahora
    codigo = _generar_texto()
    fila = {
        "codigo": _normalizar(codigo),
        "tenant": tenant,
        "creado_en": int(ahora),
        "vence_en": int(ahora + VIGENCIA),
        "revocado": False,
        "usos": 0,
    }
    _memoria[fila["codigo"]] = fila
    supabase.guardar_enrolamiento(fila)
    return {"codigo": codigo, "tenant": tenant, "vence_en": fila["vence_en"]}


def _buscar(codigo: str) -> dict | None:
    limpio = _normalizar(codigo)
    fila = _memoria.get(limpio)
    if fila is None:
        fila = supabase.leer_enrolamiento(limpio)
        if fila is not None:
            _memoria[limpio] = fila
    return fila


def canjear(codigo: str, ahora: float | None = None) -> dict | None:
    """El codigo por un token de equipo. None si no sirve, sin decir por que.

    Un solo motivo de rechazo a proposito, igual que en el login: distinguir
    "no existe" de "vencio" de "revocado" le confirma a quien prueba codigos
    cuales existieron alguna vez.
    """

    ahora = time.time() if ahora is None else ahora
    fila = _buscar(codigo)
    if fila is None or fila.get("revocado") or fila.get("vence_en", 0) <= ahora:
        return None

    fila["usos"] = int(fila.get("usos", 0)) + 1
    supabase.guardar_enrolamiento(fila)
    tenant = fila["tenant"]
    return {"tenant": tenant, "token": emitir_equipo(tenant, fila["codigo"])}


def revocar(codigo: str) -> bool:
    fila = _buscar(codigo)
    if fila is None:
        return False
    fila["revocado"] = True
    supabase.guardar_enrolamiento(fila)
    return True


def listar(tenant: str) -> list[dict]:
    """Los codigos de una empresa, para que el panel los muestre.

    El codigo va entero: el admin que lo genero tiene que poder volver a leerlo
    para pasarselo a alguien. No es un secreto que se guarde hasheado -- es un
    pasaje de un solo sentido, y quien tiene sesion en el panel ya puede hacer
    mas que canjearlo.
    """

    filas = supabase.leer_enrolamientos(tenant)
    if filas is None:
        filas = [f for f in _memoria.values() if f.get("tenant") == tenant]
    return sorted(filas, key=lambda f: f.get("creado_en", 0), reverse=True)


# -- el token de equipo ------------------------------------------------------
#
# Se firma con la misma llave del servidor que las sesiones (cuentas.py), asi
# que no hay una segunda credencial que rotar ni un segundo lugar donde
# equivocarse. Lo que cambia es lo que lleva adentro y que no vence.

# Compartir la llave obliga a que el tipo viaje adentro de la firma: ver el
# comentario de `cuentas.TIPO`, que explica por que no alcanza con que a cada
# formato le falte un campo del otro.
TIPO = "equipo"


def emitir_equipo(tenant: str, codigo: str, ahora: float | None = None) -> str:
    """El token que lleva cada equipo enrolado.

    `codigo` es obligatorio a proposito: un token de equipo que no salio de un
    enrolamiento no deberia poder existir, y es la referencia que despues
    permite darlo de baja.
    """

    return cuentas.firmar(
        {
            "tipo": TIPO,
            "tenant": tenant,
            "jti": _normalizar(codigo),
            "desde": int(time.time() if ahora is None else ahora),
        }
    )


def _dado_de_baja(jti: str) -> bool:
    """Si el enrolamiento del que salio un token esta revocado.

    Cuando la fila no aparece --Supabase caido, o el proceso recien arrancado y
    sin cache-- el token se ACEPTA. Es fail-open a proposito y vale la pena
    decir por que: la alternativa es que todos los agentes dejen de reportar
    cada vez que la base hipa, y un agente mudo es el estado que este modulo
    existe para evitar. La ventana ademas es angosta: `crear` deja la fila en
    `_memoria` y `revocar` la actualiza ahi mismo, asi que en la instancia que
    atiende los eventos la respuesta sale de memoria.
    """

    fila = _buscar(jti)
    return bool(fila and fila.get("revocado"))


def leer_equipo(token: str) -> dict | None:
    """El contenido del token de equipo si la firma es buena. None si no."""

    cuerpo = cuentas.cuerpo_firmado(token)
    resultado = None
    if cuerpo is not None:
        # `jti` se exige: un token sin el es de antes de que la revocacion
        # existiera y no se puede atar a ninguna fila. Aceptarlo seria dejar
        # viva justo la credencial que no se puede dar de baja.
        propio = cuerpo.get("tipo") == TIPO
        completo = propio and bool(cuerpo.get("tenant")) and bool(cuerpo.get("jti"))
        if completo and not _dado_de_baja(cuerpo["jti"]):
            resultado = cuerpo
    return resultado


def tenant_del_encabezado(encabezado: str | None) -> str | None:
    """La empresa a la que pertenece este equipo, segun su token.

    Es la funcion que usa /v1/events, y devuelve el TENANT y no el cuerpo entero
    para que en el sitio de la llamada no exista siquiera la tentacion de leer
    otra cosa del token y confundirla con lo que dijo el evento.
    """

    texto = (encabezado or "").strip()
    cuerpo = None
    if texto.lower().startswith("bearer "):
        cuerpo = leer_equipo(texto[7:].strip())
    return cuerpo["tenant"] if cuerpo else None
