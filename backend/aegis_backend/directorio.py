"""La empresa, su gente y las herramientas que corren en ella.

Todo esto estaba escrito a mano en el frontend: diez personas en un
`shared/data/colaboradores.ts`, un inventario de agentes inventado, y una
pantalla de registro de empresa que no mandaba nada a ningun lado. Servia para
disenar y no para operar, que es la misma distancia que separaba al panel de
mostrar datos de verdad.

La pieza que hace que esto valga algo es una sola columna: `usuario`. Es el
mismo seudonimo que el agente reporta en `actor.user_id`, asi que es la bisagra
entre una persona y sus eventos **sin que el evento lleve nunca su nombre**. El
panel puede decir "Marcos reincide con credenciales" cruzando dos tablas, y el
agente sigue sin saber quien es Marcos.

Como el resto del backend: sin dependencias nuevas, contra PostgREST, y si no
hay base configurada todo vive en memoria y el servicio arranca igual.
"""

from __future__ import annotations

from . import supabase

TABLA_TENANTS = "aegis_tenants"
TABLA_COLABORADORES = "aegis_colaboradores"
TABLA_INVENTARIO = "aegis_inventario"

ESTADOS = ("activo", "pendiente", "inactivo")
CLASES = ("agente", "mcp", "skill")

# El respaldo local, por tenant. Existe para que esto se pueda levantar y probar
# sin credenciales de nada, igual que DomainStore y PolicyStore.
_memoria: dict[str, dict[str, list[dict]]] = {}


def _local(tenant: str, tabla: str) -> list[dict]:
    return _memoria.setdefault(tenant, {}).setdefault(tabla, [])


# -- la empresa --------------------------------------------------------------


def tenant(nombre_tenant: str) -> dict | None:
    encontrado = None
    if supabase.configurado():
        filas = supabase._pedir(
            "GET", f"{TABLA_TENANTS}?tenant=eq.{nombre_tenant}&select=*&limit=1"
        )
        if filas:
            encontrado = filas[0]
    if encontrado is None:
        propios = _local(nombre_tenant, TABLA_TENANTS)
        encontrado = propios[0] if propios else None
    return encontrado


def guardar_tenant(datos: dict) -> dict:
    fila = {
        "tenant": datos.get("tenant") or "acme",
        "nombre": datos.get("nombre") or datos.get("tenant") or "acme",
        "sector": datos.get("sector"),
        "tamano": datos.get("tamano"),
        "areas": [a for a in (datos.get("areas") or []) if a],
    }
    if supabase.configurado():
        supabase._pedir(
            "POST",
            TABLA_TENANTS,
            [fila],
            {"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    propios = _local(fila["tenant"], TABLA_TENANTS)
    propios.clear()
    propios.append(fila)
    return fila


# -- la gente ----------------------------------------------------------------


def colaboradores(nombre_tenant: str) -> list[dict]:
    filas = None
    if supabase.configurado():
        filas = supabase._pedir(
            "GET",
            f"{TABLA_COLABORADORES}?tenant=eq.{nombre_tenant}&select=*&order=nombre.asc",
        )
    if filas is None:
        filas = list(_local(nombre_tenant, TABLA_COLABORADORES))
    return filas


def guardar_colaborador(nombre_tenant: str, datos: dict) -> dict | None:
    """Uno solo. None si le falta lo minimo para significar algo.

    Lo minimo es el usuario y el nombre: sin usuario no se puede cruzar con
    ningun evento, y sin nombre la fila no sirve para mostrar.
    """

    usuario = str(datos.get("usuario") or "").strip().lower()
    nombre = str(datos.get("nombre") or "").strip()
    if not usuario or not nombre:
        return None

    estado = datos.get("estado") or "pendiente"
    fila = {
        "tenant": nombre_tenant,
        "usuario": usuario,
        "nombre": nombre,
        "cargo": datos.get("cargo"),
        "area": datos.get("area"),
        "estado": estado if estado in ESTADOS else "pendiente",
    }
    if supabase.configurado():
        supabase._pedir(
            "POST",
            TABLA_COLABORADORES,
            [fila],
            {"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    propios = _local(nombre_tenant, TABLA_COLABORADORES)
    for i, existente in enumerate(propios):
        if existente["usuario"] == usuario:
            propios[i] = fila
            break
    else:
        propios.append(fila)
    return fila


def guardar_colaboradores(nombre_tenant: str, filas: list[dict]) -> list[dict]:
    """El alta masiva del CSV. Devuelve solo las que entraron.

    Las invalidas se descartan en silencio y no cancelan al resto: subir un CSV
    de cincuenta personas y que se caiga entero porque una fila no tiene usuario
    es peor que dar de alta cuarenta y nueve y decir cuantas faltaron.
    """

    guardadas = []
    for datos in filas:
        fila = guardar_colaborador(nombre_tenant, datos)
        if fila is not None:
            guardadas.append(fila)
    return guardadas


def borrar_colaborador(nombre_tenant: str, usuario: str) -> None:
    usuario = usuario.strip().lower()
    if supabase.configurado():
        supabase._pedir(
            "DELETE",
            f"{TABLA_COLABORADORES}?tenant=eq.{nombre_tenant}&usuario=eq.{usuario}",
            None,
            {"Prefer": "return=minimal"},
        )
    propios = _local(nombre_tenant, TABLA_COLABORADORES)
    propios[:] = [c for c in propios if c["usuario"] != usuario]


# -- las herramientas --------------------------------------------------------


def inventario(nombre_tenant: str) -> list[dict]:
    filas = None
    if supabase.configurado():
        filas = supabase._pedir(
            "GET",
            f"{TABLA_INVENTARIO}?tenant=eq.{nombre_tenant}&select=*&order=nombre.asc",
        )
    if filas is None:
        filas = list(_local(nombre_tenant, TABLA_INVENTARIO))
    return filas


def guardar_en_inventario(nombre_tenant: str, datos: dict) -> dict | None:
    nombre = str(datos.get("nombre") or "").strip()
    clase = datos.get("clase")
    if not nombre or clase not in CLASES:
        return None

    fila = {
        "tenant": nombre_tenant,
        "clase": clase,
        "nombre": nombre,
        "tipo": datos.get("tipo"),
        "estado": datos.get("estado") or "no-catalogado",
        "alcance": datos.get("alcance"),
        "usuarios": [u for u in (datos.get("usuarios") or []) if u],
        "ultima_actividad": datos.get("ultima_actividad"),
    }
    if supabase.configurado():
        supabase._pedir(
            "POST",
            TABLA_INVENTARIO,
            [fila],
            {"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    propios = _local(nombre_tenant, TABLA_INVENTARIO)
    for i, existente in enumerate(propios):
        if (existente["clase"], existente["nombre"]) == (clase, nombre):
            propios[i] = fila
            break
    else:
        propios.append(fila)
    return fila


def descubrir_desde_eventos(nombre_tenant: str, eventos: list[dict]) -> list[dict]:
    """Lo que el inventario no puede inventar: lo que de verdad esta corriendo.

    El Agent Inventory del panel listaba herramientas escritas a mano. Pero el
    agente ya sabe cuales hay: cada evento trae `destination.process`, y ese
    campo es exactamente "que herramienta hizo este envio".

    Lo que aparece asi entra como `no-catalogado`, que es la definicion misma de
    shadow AI: una herramienta que nadie aprobo y que se delato usandose. Lo que
    ya estaba catalogado no se pisa -alguien decidio su estado a mano- y por eso
    esto devuelve solo lo nuevo.
    """

    conocidos = {f["nombre"] for f in inventario(nombre_tenant) if f["clase"] == "agente"}
    vistos: dict[str, set[str]] = {}
    for evento in eventos:
        proceso = (evento.get("destination") or {}).get("process") or ""
        if proceso and proceso != "desconocido" and proceso not in conocidos:
            usuario = (evento.get("actor") or {}).get("user_id") or ""
            vistos.setdefault(proceso, set())
            if usuario:
                vistos[proceso].add(usuario)

    nuevos = []
    for proceso, usuarios in sorted(vistos.items()):
        fila = guardar_en_inventario(
            nombre_tenant,
            {
                "clase": "agente",
                "nombre": proceso,
                "tipo": "CLI" if "-" in proceso or "code" in proceso else "Navegador",
                "estado": "no-catalogado",
                "usuarios": sorted(usuarios),
            },
        )
        if fila is not None:
            nuevos.append(fila)
    return nuevos
