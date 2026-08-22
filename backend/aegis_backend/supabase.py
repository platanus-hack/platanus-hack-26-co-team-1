"""Supabase como el almacen duradero de Aegis.

Hasta aca el servicio desplegado guardaba en memoria: el plan gratuito de Render
no tiene disco, asi que cada reinicio -y el plan gratuito reinicia solo cuando
nadie entra un rato- se llevaba todo. El panel tapaba el hueco mostrando una
semana simulada, que sirve para ensenar el producto y no para operarlo. Esto es
lo que hace la diferencia entre las dos cosas.

Cuatro decisiones que valen mas que el codigo:

1. **Sin dependencias nuevas.** `requirements.txt` esta vacio a proposito: el
   servicio arranca con Python pelado. PostgREST -el API que Supabase pone
   delante de la base- es HTTP con JSON, que es exactamente lo que este
   repositorio ya sabia hacer para hablar con el KV. Meter `supabase-py` o
   `psycopg2` cambiaria el build entero por una comodidad de sintaxis.

2. **Lista blanca en el borde, no lista negra.** `lleva_contenido` rechaza
   eventos con campos prohibidos, y esta bien para rechazar. Pero mandar a un
   tercero hospedado pide lo contrario: se proyectan **solo** las columnas
   conocidas. Si manana alguien agrega un campo al evento, no se sube por
   omision en vez de filtrarse por descuido.

3. **La tabla no tiene columna donde poner el contenido.** Es la garantia mas
   fuerte de las tres, porque no depende de que este codigo este bien: aunque
   la lista blanca se rompiera, en el esquema no hay lugar donde escribirlo.

4. **El navegador nunca habla con Supabase.** No hay `anon key` en el front. Si
   la hubiera, cualquiera con el panel abierto podria leerse la tabla entera
   desde la consola. Todo pasa por /api/metrics, que corre en el servidor con la
   `service_role` que nunca sale de las variables de entorno de Render.

Y sobre todo lo demas: si Supabase no responde, esto devuelve None y quien llama
sigue con lo que tenia. Un almacen caido degrada el panel, nunca lo tumba.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import secretos

TIMEOUT = 6

# El interruptor que apaga todo esto, y por que existe.
#
# Las credenciales viven en ~/.aegis/secretos.env, que es del HOME de quien
# corre la suite. Sin este interruptor, el dia que alguien configura Supabase su
# suite empieza a escribir en la base de VERDAD: los tests que crean un
# DomainStore y le meten un veredicto suben "ia-magica.co" a la tabla que usa la
# demo. Es el mismo acoplamiento que ya costo veintitres tests rojos cuando la
# suite escribia ~/.aegis/politica.json (ver docs/ESTADO.md, seccion 5), con el
# agravante de que esta vez ensucia produccion.
#
# Va aca y no en cada test a proposito: en un test hay que acordarse, y quien
# escriba el proximo no tiene por que saber que existe este problema.
APAGADO = "AEGIS_SUPABASE_DISABLED"
TABLA_EVENTOS = "aegis_eventos"
TABLA_DOMINIOS = "aegis_dominios"
TABLA_POLITICAS = "aegis_politicas"


def _url() -> str:
    return secretos.cargar("SUPABASE_URL").rstrip("/")


def _clave() -> str:
    """La clave `service_role`, del entorno o de ~/.aegis/secretos.env.

    Sale del mismo lugar que la de Anthropic y por el mismo motivo (ver
    secretos.py): en Render la pone la variable de entorno del servicio, y en una
    maquina de desarrollo el archivo, para no tener que pegarla en ningun lado
    donde quede escrita.

    Y es la `service_role` a proposito, no la `anon`: las tablas tienen RLS
    prendida sin politicas, asi que la anon no puede tocar nada. La service_role
    nunca sale del servidor -el navegador jamas habla con Supabase- porque con
    ella se lee el diccionario de terminos de la empresa, que es la lista mas
    sensible que hay en todo el sistema.
    """

    valor = ""
    for nombre in ("SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        if not valor:
            valor = secretos.cargar(nombre)
    return valor


def configurado() -> bool:
    """Las dos se resuelven en cada llamada y no al importar.

    Es lo mismo que hacen policy_store y lessons, y por el mismo motivo: quien
    configure Supabase despues de que el modulo se importo tiene que verlo sin
    reiniciar nada.
    """

    apagado = bool(os.environ.get(APAGADO, "").strip())
    return not apagado and bool(_url() and _clave())


def _pedir(metodo: str, camino: str, cuerpo=None, cabeceras: dict | None = None):
    """Una llamada a PostgREST. None si algo falla, y nunca una excepcion.

    Quien llama decide que hacer sin el dato; nadie deberia quedarse sin panel
    porque un servicio de terceros tardo.
    """

    if not configurado():
        return None

    clave = _clave()
    cuerpo_serializado = None
    if cuerpo is not None:
        cuerpo_serializado = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")

    peticion = urllib.request.Request(
        f"{_url()}/rest/v1/{camino}",
        method=metodo,
        data=cuerpo_serializado,
        headers={
            "apikey": clave,
            "Authorization": f"Bearer {clave}",
            "Content-Type": "application/json",
            **(cabeceras or {}),
        },
    )
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT) as respuesta:
            crudo = respuesta.read()
            resultado = json.loads(crudo) if crudo.strip() else []
    except (urllib.error.URLError, OSError, ValueError):
        resultado = None
    return resultado


# -- eventos ----------------------------------------------------------------
#
# La forma que viaja por la red es la del contrato (agent/aegis_agent/events.py):
# anidada, con actor / destination / detection. La que entra a la base es plana,
# porque una tabla plana se consulta y se indexa; y la que sale vuelve a ser la
# anidada, para que compute() y el panel no se enteren de nada de esto.


def _a_fila(evento: dict) -> dict:
    """La lista blanca. Lo que no esta nombrado aca no sale del servicio."""

    actor = evento.get("actor") or {}
    destino = evento.get("destination") or {}
    deteccion = evento.get("detection") or {}
    stats = evento.get("payload_stats") or {}
    evidencia = (deteccion.get("evidence") or "")[:32]

    return {
        "event_id": evento.get("event_id"),
        "tenant_id": evento.get("tenant_id") or "acme",
        "ocurrido_en": evento.get("occurred_at"),
        "accion": evento.get("action"),
        "user_id": actor.get("user_id"),
        "area": actor.get("area"),
        "rol": actor.get("role"),
        "dominio": destino.get("domain"),
        "clasificacion": destino.get("classification"),
        "proceso": destino.get("process"),
        "regla": deteccion.get("rule_id"),
        "categoria": deteccion.get("category"),
        "severidad": deteccion.get("severity"),
        "confianza": deteccion.get("confidence"),
        "motor": deteccion.get("engine"),
        # La evidencia es una etiqueta -"<email>", "AKIA****"- y el servicio ya
        # rechaza cualquiera de mas de 32 caracteres. Se recorta igual: es la
        # unica columna donde un bug de otro lado podria colar texto real.
        "evidencia": evidencia or None,
        "bytes": stats.get("bytes"),
        "truncado": stats.get("truncated"),
        "agente": evento.get("agent_version"),
    }


def _a_evento(fila: dict) -> dict:
    """De la fila plana al contrato, para que el panel no cambie ni una linea."""

    deteccion = None
    if fila.get("regla"):
        deteccion = {
            "rule_id": fila.get("regla"),
            "category": fila.get("categoria"),
            "severity": fila.get("severidad"),
            "confidence": fila.get("confianza"),
            "engine": fila.get("motor"),
            "evidence": fila.get("evidencia"),
        }

    return {
        "event_id": fila.get("event_id"),
        "tenant_id": fila.get("tenant_id"),
        "actor": {
            "user_id": fila.get("user_id"),
            "area": fila.get("area"),
            "role": fila.get("rol"),
        },
        "destination": {
            "domain": fila.get("dominio"),
            "classification": fila.get("clasificacion"),
            "process": fila.get("proceso"),
        },
        "detection": deteccion,
        "action": fila.get("accion"),
        "payload_stats": {
            "bytes": fila.get("bytes"),
            "truncated": fila.get("truncado"),
        },
        "occurred_at": fila.get("ocurrido_en"),
        "agent_version": fila.get("agente"),
    }


def guardar_evento(evento: dict) -> bool:
    # merge-duplicates y no un insert pelado: el agente reintenta la cola cuando
    # el panel vuelve, y sin esto el mismo event_id entraria dos veces e
    # inflaria las metricas justo despues de una caida.
    respuesta = _pedir(
        "POST",
        TABLA_EVENTOS,
        [_a_fila(evento)],
        {"Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    return respuesta is not None


def leer_eventos(limite: int = 5000, tenant: str | None = None) -> list[dict] | None:
    """Los eventos, opcionalmente de una sola empresa.

    El filtro se aplica **en la consulta** y no despues de traer todo: si se
    filtrara en Python, los datos de las demas empresas igual habrian viajado
    por la red y estarian en la memoria del proceso que atiende a una sola. El
    aislamiento tiene que empezar donde estan los datos.
    """

    filtro = f"&tenant_id=eq.{tenant}" if tenant else ""
    filas = _pedir(
        "GET",
        f"{TABLA_EVENTOS}?select=*{filtro}&order=ocurrido_en.desc&limit={limite}",
    )
    eventos = None
    if filas is not None:
        eventos = [_a_evento(f) for f in filas]
    return eventos


# -- veredictos de dominio ---------------------------------------------------


def guardar_veredicto(datos: dict) -> bool:
    respuesta = _pedir(
        "POST",
        TABLA_DOMINIOS,
        [datos],
        {"Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    return respuesta is not None


def leer_veredictos() -> dict | None:
    filas = _pedir("GET", f"{TABLA_DOMINIOS}?select=*")
    veredictos = None
    if filas is not None:
        veredictos = {f["domain"]: f for f in filas if f.get("domain")}
    return veredictos


# -- politicas ---------------------------------------------------------------


def guardar_politica(tenant: str, datos: dict) -> bool:
    respuesta = _pedir(
        "POST",
        TABLA_POLITICAS,
        [{"tenant": tenant, "datos": datos}],
        {"Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    return respuesta is not None


def leer_politicas() -> dict | None:
    filas = _pedir("GET", f"{TABLA_POLITICAS}?select=tenant,datos")
    politicas = None
    if filas is not None:
        politicas = {f["tenant"]: f.get("datos") or {} for f in filas if f.get("tenant")}
    return politicas
