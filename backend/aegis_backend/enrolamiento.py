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
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
    return {"tenant": tenant, "token": emitir_equipo(tenant)}


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


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _des64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def emitir_equipo(tenant: str, ahora: float | None = None) -> str:
    cuerpo = {
        "tipo": "equipo",
        "tenant": tenant,
        "desde": int(time.time() if ahora is None else ahora),
    }
    crudo = _b64(json.dumps(cuerpo, separators=(",", ":")).encode())
    firma = hmac.new(
        cuentas._firma_del_servidor(), crudo.encode(), hashlib.sha256
    ).digest()
    return f"{crudo}.{_b64(firma)}"


def leer_equipo(token: str) -> dict | None:
    """El contenido del token de equipo si la firma es buena. None si no."""

    resultado = None
    partes = (token or "").split(".")
    if len(partes) == 2:
        crudo, firma = partes
        esperada = hmac.new(
            cuentas._firma_del_servidor(), crudo.encode(), hashlib.sha256
        ).digest()
        # compare_digest y no ==: comparar firmas con == filtra por tiempo en
        # que byte se rompio la igualdad.
        if hmac.compare_digest(_b64(esperada), firma):
            try:
                cuerpo = json.loads(_des64(crudo))
            except (ValueError, TypeError):
                cuerpo = None
            if cuerpo and cuerpo.get("tipo") == "equipo" and cuerpo.get("tenant"):
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
