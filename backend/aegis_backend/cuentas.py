"""Quien entra al panel, y de que empresa son los datos que ve.

Hasta aca el panel era publico. `/admin/panel` lo abria cualquiera y mostraba
**todos** los eventos, de todos los tenants, porque nada los separaba: el
contrato tiene `tenant_id` desde el primer dia y ninguna consulta lo miraba.
Para un producto cuyo pitch es "tus datos no salen de tu empresa", que el panel
de una empresa muestre el trafico de otra no es un detalle de permisos: es el
producto al reves.

Tres decisiones, y la primera es la que sostiene todo:

1. **El tenant sale del token, nunca del pedido.** Si viniera en la URL o en el
   cuerpo -`/api/metrics?tenant=otra`- cualquier cuenta leeria los datos de
   cualquier otra cambiando un parametro, y no habria login que lo arregle. El
   token se firma en el servidor con el tenant adentro; el cliente lo lleva y no
   lo puede editar sin romper la firma.

2. **La contrasena no se guarda.** Se guarda `scrypt(contrasena, sal)`, con una
   sal distinta por cuenta. scrypt esta en la biblioteca estandar y es caro a
   proposito: quien se lleve la tabla no puede probar millones de candidatas por
   segundo. Sin dependencias nuevas, como el resto del backend.

3. **Comparar en tiempo constante.** `hmac.compare_digest` y no `==`, tanto para
   el hash como para la firma del token. Comparar con `==` corta en el primer
   byte distinto, y ese tiempo se puede medir para adivinar la firma byte por
   byte.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from . import secretos, supabase

TABLA = "aegis_cuentas"

# Ocho horas: una jornada. Mas corto molesta al que deja el panel abierto en una
# pantalla; mas largo deja sesiones vivas de gente que ya no trabaja aca.
VIGENCIA = 8 * 3600

# Que clase de credencial es esta, DENTRO de la firma.
#
# Las sesiones de persona y los tokens de equipo (enrolamiento.py) comparten
# llave y formato de cable. Hasta aca lo unico que impedia usar uno como el otro
# eran dos chequeos que no se pusieron para eso: a la sesion se le exige `vence`
# --que el token de equipo no lleva-- y al de equipo se le exige `tipo`. Es
# decir que la separacion era una casualidad, no una decision.
#
# Y era una casualidad a punto de romperse: darle expiracion al token de equipo
# es la mitad natural de hacerlo revocable, y el dia que alguien la agregue ese
# token pasa a ser una sesion valida. Sin `rol`, ademas, que es peor de lo que
# suena. Un claim explicito que los dos lectores exigen lo cierra de una vez.
TIPO = "sesion"

# Los roles que existen, y cual se supone cuando la fila no dice.
#
# El default es el de MENOS permiso a proposito. Antes era "admin" --
# `cuenta.get("rol", "admin")`-- y eso es un default abierto: una fila a la que
# le falte el campo, por una migracion a medias o por una escritura directa a la
# tabla, sale administradora. El sentido de un default es cubrir el caso que no
# se penso, y el caso que no se penso no deberia poder escribir.
ADMIN = "admin"
LECTOR = "lector"
ROL_POR_DEFECTO = LECTOR


def rol_de(cuenta: dict | None) -> str:
    """El rol de una cuenta o de una sesion, con el default cerrado."""

    return (cuenta or {}).get("rol") or ROL_POR_DEFECTO


def puede_escribir(sesion: dict | None) -> bool:
    """Si esta sesion puede cambiar algo, y no solo mirarlo.

    Existe porque hasta aca el rol se emitia, se guardaba y se devolvia, y no se
    comparaba en ningun lado: cualquier sesion valida podia llamar cualquier
    escritura, incluida la que emite codigos de enrolamiento nuevos. No era
    explotable --todas las cuentas se crean admin-- pero un campo de
    autorizacion que existe invita a confiar en el, y el frontend lo recibe.
    """

    return rol_de(sesion) == ADMIN

# Parametros de scrypt. n=16384 tarda ~50 ms por intento en un portatil, que es
# invisible para quien entra una vez al dia y carisimo para quien prueba una
# lista de contrasenas.
_N, _R, _P = 16384, 8, 1


def _firma_del_servidor() -> bytes:
    """La clave con la que se firman los tokens.

    Si no hay ninguna configurada se genera una al azar **por proceso**: el
    efecto es que al reiniciar el servicio caducan todas las sesiones, que es
    molesto pero seguro. Lo inaceptable seria una constante en el codigo, porque
    entonces cualquiera que lea el repositorio se firma sus propios tokens.
    """

    puesta = secretos.cargar("AEGIS_FIRMA")
    return puesta.encode() if puesta else _POR_PROCESO


_POR_PROCESO = secrets.token_bytes(32)


# -- contrasenas -------------------------------------------------------------


def hashear(contrasena: str, sal: str | None = None) -> tuple[str, str]:
    sal = sal or secrets.token_hex(16)
    bruto = hashlib.scrypt(
        contrasena.encode("utf-8"), salt=sal.encode(), n=_N, r=_R, p=_P, dklen=32
    )
    return bruto.hex(), sal


def coincide(contrasena: str, esperado: str, sal: str) -> bool:
    calculado, _ = hashear(contrasena, sal)
    return hmac.compare_digest(calculado, esperado)


# -- tokens ------------------------------------------------------------------


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _des64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def firmar(cuerpo: dict) -> str:
    """Un cuerpo en un token firmado: `base64(json).base64(hmac)`.

    Vive aca --y no una copia en cada modulo que emite algo-- porque escribir la
    misma primitiva de seguridad dos veces significa arreglarla en un lado y no
    en el otro. Estaba duplicada palabra por palabra en `enrolamiento.py`.
    """

    crudo = _b64(json.dumps(cuerpo, separators=(",", ":")).encode())
    firma = hmac.new(_firma_del_servidor(), crudo.encode(), hashlib.sha256).digest()
    return f"{crudo}.{_b64(firma)}"


def cuerpo_firmado(token: str) -> dict | None:
    """Lo que dice el token si la firma es buena. None si no.

    NO decide si el token sirve: eso depende de para que se lo pida cada quien
    --una sesion mira `vence`, un equipo mira que no lo hayan dado de baja-- y
    esa parte se queda en cada modulo. Lo que se comparte es lo que no puede
    salir distinto en dos lados: verificar la firma.
    """

    resultado = None
    partes = (token or "").split(".")
    if len(partes) == 2:
        crudo, firma = partes
        esperada = hmac.new(
            _firma_del_servidor(), crudo.encode(), hashlib.sha256
        ).digest()
        # compare_digest y no ==: comparar firmas con == filtra por tiempo en
        # que byte se rompio la igualdad, y con eso se adivinan de a un byte.
        if hmac.compare_digest(_b64(esperada), firma):
            try:
                resultado = json.loads(_des64(crudo))
            except (ValueError, TypeError):
                resultado = None
    return resultado if isinstance(resultado, dict) else None


def emitir(usuario: str, tenant: str, rol: str, ahora: float | None = None) -> str:
    """Un token firmado: quien es, de que empresa, y hasta cuando."""

    cuerpo = {
        "tipo": TIPO,
        "usuario": usuario,
        "tenant": tenant,
        "rol": rol,
        "vence": int((ahora or time.time()) + VIGENCIA),
    }
    return firmar(cuerpo)


def leer(token: str, ahora: float | None = None) -> dict | None:
    """El contenido del token si la firma es buena y no vencio. None si no."""

    cuerpo = cuerpo_firmado(token)
    resultado = None
    if cuerpo is not None:
        vigente = cuerpo.get("vence", 0) > (ahora or time.time())
        # El tipo se exige, no se infiere. Ver TIPO arriba.
        if vigente and cuerpo.get("tipo") == TIPO:
            resultado = cuerpo
    return resultado


def del_encabezado(encabezado: str | None, ahora: float | None = None) -> dict | None:
    """Lo mismo, desde un `Authorization: Bearer ...`."""

    texto = (encabezado or "").strip()
    if texto.lower().startswith("bearer "):
        cuerpo = leer(texto[7:].strip(), ahora)
    else:
        cuerpo = None
    return cuerpo


# -- el almacen de cuentas ---------------------------------------------------
#
# Va contra Supabase igual que todo lo demas, con el mismo respaldo local: sin
# base, las cuentas viven en memoria y alcanza para levantar esto y probarlo.

_memoria: dict[str, dict] = {}


def guardar(usuario: str, contrasena: str, tenant: str, rol: str = "admin") -> dict:
    hash_, sal = hashear(contrasena)
    fila = {
        "usuario": usuario.strip().lower(),
        "tenant": tenant,
        "rol": rol,
        "hash": hash_,
        "sal": sal,
    }
    if supabase.configurado():
        supabase._pedir(
            "POST",
            TABLA,
            [fila],
            {"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    _memoria[fila["usuario"]] = fila
    return fila


def buscar(usuario: str) -> dict | None:
    clave = (usuario or "").strip().lower()
    encontrada = None
    if supabase.configurado():
        filas = supabase._pedir("GET", f"{TABLA}?usuario=eq.{clave}&select=*&limit=1")
        if filas:
            encontrada = filas[0]
    return encontrada or _memoria.get(clave)


def autenticar(usuario: str, contrasena: str) -> dict | None:
    """La cuenta si las credenciales son buenas, None si no.

    Devuelve None por las dos razones -no existe, o la contrasena no va- a
    proposito: distinguirlas le dice a quien prueba cuales usuarios existen.
    """

    cuenta = buscar(usuario)
    valida = None
    if cuenta and coincide(contrasena, cuenta.get("hash", ""), cuenta.get("sal", "")):
        valida = cuenta
    return valida


def sembrar_si_no_hay(usuario: str, contrasena: str, tenant: str) -> bool:
    """Crea la cuenta inicial si todavia no existe. True si la creo.

    No pisa una existente: si alguien ya cambio la contrasena, arrancar el
    servicio no puede devolverla a la de fabrica.
    """

    nueva = buscar(usuario) is None
    if nueva:
        guardar(usuario, contrasena, tenant)
    return nueva


def cuenta_inicial() -> tuple[str, str, str]:
    """Usuario, contrasena y tenant de la cuenta que se siembra al arrancar."""

    return (
        os.environ.get("AEGIS_ADMIN_USUARIO", "admin"),
        secretos.cargar("AEGIS_ADMIN_PASSWORD") or "admin",
        os.environ.get("AEGIS_TENANT", "acme"),
    )
