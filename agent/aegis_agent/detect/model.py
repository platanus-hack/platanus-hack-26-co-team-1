from __future__ import annotations

import os
import threading
import time

from .types import Finding

# Nivel T2 de la cascada: el modelo local.
#
# Existe para lo que ninguna regla puede ver. T1 encuentra una llave de AWS
# porque tiene un formato; no encuentra "el cliente Bancolombia esta renegociando
# el contrato de nomina" porque eso no tiene formato, tiene sentido.
#
# Tres cosas que gobiernan este archivo:
#
#   1. No es un LLM. Es un extractor de entidades de ~50M de parametros que corre
#      en CPU. Un LLM local serian gigabytes y segundos, y esto esta en el camino
#      critico de cada envio.
#   2. Solo corre cuando T1 no encontro nada. Si ya hay una credencial detectada,
#      gastar 150 ms mas no cambia la decision.
#   3. Si no esta instalado, el agente funciona igual. Nunca es un requisito.

# Etiquetas en espanol: el modelo las recibe como texto, asi que agregar un tipo
# de dato es configuracion de la empresa y no un release del producto.
#
# CUALES, esta medido sobre el corpus de bench/corpus.py (25 frases sensibles y
# 36 de trabajo normal), etiqueta por etiqueta. El resultado corrigio dos cosas
# que este archivo daba por sabidas:
#
#   1. "empresa" y "organizacion" encuentran mucho (13/25) pero ensucian mucho
#      mas (6/36): marcan "explicame que hace Bancolombia como negocio" igual
#      que marcan un contrato. Un extractor de entidades no distingue mencionar
#      de filtrar. "nombre de cliente" encuentra 9/25 con 1/36, que es la unica
#      relacion que aguanta una decision.
#   2. La etiqueta corta NO siempre gana. "nombre de cliente" es mas precisa que
#      "empresa" y "condicion de salud" mas limpia que "enfermedad". Lo que
#      importa no es el largo sino que la etiqueta nombre la relacion, no la cosa.
#
# Se sacaron las que no encuentran nada: "contrasena", "clave", "clave de acceso"
# y "diagnostico medico" dieron 0/25. Las credenciales dichas en lenguaje natural
# las ve T1 con la regla credencial_en_espanol, que es determinista.
# Hay dos clases de etiqueta y la diferencia es cuanta autoridad tienen, no que
# buscan. Las precisas pueden cortar un envio. Las amplias encuentran mucho mas
# pero se equivocan seguido, asi que solo avisan: el envio sale igual y el
# hallazgo queda en el panel, que es de donde salen las lecciones.
#
# Avisar no le cuesta nada a la persona (no ve ningun cartel, no se frena su
# trabajo) y le da al panel la visibilidad que si necesita la empresa. Por eso
# vale la pena tolerar que una etiqueta amplia se equivoque.
ETIQUETAS_PRECISAS = ("nombre de cliente",)

ETIQUETAS_AMPLIAS = (
    "empresa",
    "dinero",
    "persona",
    "empleado",
    "domicilio",
    "condicion de salud",
    "credencial",
)

ETIQUETAS_POR_DEFECTO = ETIQUETAS_PRECISAS + ETIQUETAS_AMPLIAS

# Medido con el conjunto de arriba sobre el corpus completo, dandole al modelo el
# prompt ya extraido y no el JSON del request:
#
#   umbral   detecta    bloquea trabajo normal
#     0.5     12/25            1/36
#     0.6      8/25            1/36
#     0.7      8/25            0/36
#
# Con las etiquetas viejas la misma medicion daba 22/25 detectando pero 9/36
# bloqueando trabajo legitimo, que es una forma rapida de que desinstalen Aegis.
#
# Se deja 0.5: detecta mas y el unico caso que bloquea de mas es el mismo en los
# tres umbrales. La medicion vieja de este archivo (7/7 con cero falsos) estaba
# hecha sobre diecisiete frases y sobre el body crudo; no describia nada real.
UMBRAL_POR_DEFECTO = 0.5

# Presupuesto duro. Si el modelo tarda mas, se descarta su respuesta y queda lo
# de T1. Medido en CPU sin GPU: p50 108 ms, p95 118 ms.
LATENCIA_MAXIMA_MS = 700

# Cuanto texto se le da. El resto ya lo miro T1 con reglas.
MAX_CARACTERES = 4000

MODELO_POR_DEFECTO = "urchade/gliner_multi-v2.1"

# Las etiquetas que, cuando el modelo las ve, valen como dato de la empresa y no
# como dato personal suelto.
# A que categoria equivale cada etiqueta, y por lo tanto que puede llegar a
# cortar un envio. Solo entra en una categoria que bloquea la etiqueta que midio
# bien: "nombre de cliente" es la unica que separa el contrato del cliente de la
# mencion casual de una marca. Todo lo demas avisa.
_CATEGORIA_POR_ETIQUETA = {
    "nombre de cliente": ("internal_data", "high"),
    "empresa": ("internal_data", "high"),
    "dinero": ("internal_data", "high"),
    "credencial": ("pii", "high"),
    "condicion de salud": ("pii", "high"),
    "empleado": ("pii", "medium"),
    "domicilio": ("pii", "medium"),
}


def etiqueta_de(rule_id: str) -> str:
    """La etiqueta que origino un hallazgo, a partir de su rule_id.

    scan_model arma el rule_id cambiando los espacios por guiones bajos; esto lo
    deshace para que la politica pueda hablar de etiquetas y no de rule_ids.
    """

    return rule_id.removeprefix("modelo:").replace("_", " ")

_lock = threading.Lock()
_modelo = None
_cargado = False

# Metricas de cuanto opina el modelo. Existen porque un modelo que en
# produccion empieza a tardar (o que dejo de cargar) se degrada en silencio: T2
# deja de proteger y nadie lo nota hasta que alguien pregunta por que nunca
# encuentra nada. Con esto, estado() lo puede mostrar.
_metricas_lock = threading.Lock()
MAX_LATENCIAS_GUARDADAS = 200
_invocaciones = 0
_hallazgos_totales = 0
_descartes_por_latencia = 0
_latencias_ms: list[float] = []


def habilitado() -> bool:
    """El modelo es opcional y se prende explicitamente.

    Arrancar descargando medio giga la primera vez que alguien abre un chat seria
    una forma rara de presentarse.
    """

    return os.environ.get("AEGIS_T2", "").strip().lower() in ("1", "true", "si", "on")


def disponible() -> bool:
    try:
        import gliner  # noqa: F401

        return True
    except ImportError:
        return False


def cargar(nombre: str = "") -> object | None:
    """Carga el modelo una sola vez, en el primer uso y no al importar."""

    global _modelo, _cargado
    with _lock:
        if not _cargado:
            _cargado = True
            try:
                from gliner import GLiNER

                _modelo = GLiNER.from_pretrained(
                    nombre or os.environ.get("AEGIS_T2_MODELO", MODELO_POR_DEFECTO)
                )
            except Exception:
                # Falta el paquete, no hay red, el modelo no existe: en todos los
                # casos el agente sigue protegiendo con T1.
                _modelo = None
    return _modelo


def _severidad(etiqueta: str) -> tuple[str, str]:
    return _CATEGORIA_POR_ETIQUETA.get(etiqueta, ("pii", "medium"))


def scan_model(
    texto: str,
    etiquetas: tuple[str, ...] = ETIQUETAS_POR_DEFECTO,
    umbral: float = UMBRAL_POR_DEFECTO,
) -> list[Finding]:
    """Hallazgos del modelo local. Lista vacia si no esta o si tarda demasiado."""

    hallazgos: list[Finding] = []
    modelo = cargar() if habilitado() else None

    if modelo is not None and texto.strip():
        recorte = texto[:MAX_CARACTERES]
        inicio = time.perf_counter()
        try:
            entidades = modelo.predict_entities(recorte, list(etiquetas), threshold=umbral)
        except Exception:
            entidades = []
        transcurrido = (time.perf_counter() - inicio) * 1000

        if transcurrido <= LATENCIA_MAXIMA_MS:
            vistas: set[str] = set()
            for entidad in entidades:
                etiqueta = entidad.get("label", "")
                if etiqueta not in vistas:
                    vistas.add(etiqueta)
                    categoria, severidad = _severidad(etiqueta)
                    hallazgos.append(
                        Finding(
                            rule_id=f"modelo:{etiqueta.replace(' ', '_')}",
                            category=categoria,
                            severity=severidad,
                            confidence=round(float(entidad.get("score", umbral)), 2),
                            # El texto detectado no sale nunca: solo el tipo, igual
                            # que con las reglas de datos personales.
                            evidence=f"<{etiqueta.split()[0]}>"[:32],
                            start=int(entidad.get("start", 0)),
                            end=int(entidad.get("end", 0)),
                        )
                    )
            _registrar_invocacion(transcurrido, descartada=False, hallazgos=len(hallazgos))
        else:
            _registrar_invocacion(transcurrido, descartada=True, hallazgos=0)

    return hallazgos


def _registrar_invocacion(latencia_ms: float, *, descartada: bool, hallazgos: int) -> None:
    """Suma una corrida del modelo a las metricas que expone estado()."""

    global _invocaciones, _hallazgos_totales, _descartes_por_latencia
    with _metricas_lock:
        _invocaciones += 1
        _hallazgos_totales += hallazgos
        if descartada:
            _descartes_por_latencia += 1
        _latencias_ms.append(latencia_ms)
        exceso = len(_latencias_ms) - MAX_LATENCIAS_GUARDADAS
        if exceso > 0:
            del _latencias_ms[:exceso]


def _p95(latencias: list[float]) -> float:
    """Percentil 95 sobre las latencias guardadas. 0.0 si todavia no hay ninguna."""

    resultado = 0.0
    if latencias:
        ordenadas = sorted(latencias)
        indice = min(len(ordenadas) - 1, round(0.95 * (len(ordenadas) - 1)))
        resultado = ordenadas[indice]
    return resultado


def reiniciar_metricas() -> None:
    """Vuelve las metricas a cero. Para que los tests no arrastren estado entre si."""

    global _invocaciones, _hallazgos_totales, _descartes_por_latencia
    with _metricas_lock:
        _invocaciones = 0
        _hallazgos_totales = 0
        _descartes_por_latencia = 0
        _latencias_ms.clear()


def estado() -> dict:
    with _metricas_lock:
        latencias = list(_latencias_ms)
        invocaciones = _invocaciones
        hallazgos_totales = _hallazgos_totales
        descartes = _descartes_por_latencia

    return {
        "habilitado": habilitado(),
        "instalado": disponible(),
        "cargado": _modelo is not None,
        "modelo": os.environ.get("AEGIS_T2_MODELO", MODELO_POR_DEFECTO),
        "umbral": UMBRAL_POR_DEFECTO,
        "presupuesto_ms": LATENCIA_MAXIMA_MS,
        "invocaciones": invocaciones,
        "hallazgos": hallazgos_totales,
        "descartes_por_latencia": descartes,
        "latencia_p95_ms": round(_p95(latencias), 1),
    }
