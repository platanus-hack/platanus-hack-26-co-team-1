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
# Van cortas a proposito. Medido con este mismo modelo: "nombre de cliente o
# empresa" daba 0.37 sobre la palabra equivocada, y "empresa" da 0.70 sobre
# "Grupo Exito". Lo mismo con salud: "diagnostico medico" no encontraba nada y
# "enfermedad" da 0.87 sobre "hipertension". Una etiqueta descriptiva se lee
# bien en el codigo y le funciona peor al modelo.
ETIQUETAS_POR_DEFECTO = (
    "persona",
    "empresa",
    "organizacion",
    "direccion",
    "dinero",
    "enfermedad",
    "contrasena",
)

# Medido con bench/evaluar_modelo sobre 7 frases sensibles y 10 de trabajo normal
# en espanol: 0.5 detecta 7/7, 0.6 detecta 6/7 y 0.75 detecta 4/7, los tres con
# CERO falsos positivos. El corpus es chico, asi que se deja 0.6 por margen; con
# un corpus real de la empresa esto se decide con datos y no con prudencia.
UMBRAL_POR_DEFECTO = 0.6

# Presupuesto duro. Si el modelo tarda mas, se descarta su respuesta y queda lo
# de T1. Medido en CPU sin GPU: p50 108 ms, p95 118 ms.
LATENCIA_MAXIMA_MS = 700

# Cuanto texto se le da. El resto ya lo miro T1 con reglas.
MAX_CARACTERES = 4000

MODELO_POR_DEFECTO = "urchade/gliner_multi-v2.1"

# Las etiquetas que, cuando el modelo las ve, valen como dato de la empresa y no
# como dato personal suelto.
_CATEGORIA_POR_ETIQUETA = {
    "contrasena": ("secret", "critical"),
    "empresa": ("internal_data", "high"),
    "organizacion": ("internal_data", "high"),
    "dinero": ("internal_data", "high"),
    "enfermedad": ("pii", "high"),
}

_lock = threading.Lock()
_modelo = None
_cargado = False


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

    return hallazgos


def estado() -> dict:
    return {
        "habilitado": habilitado(),
        "instalado": disponible(),
        "cargado": _modelo is not None,
        "modelo": os.environ.get("AEGIS_T2_MODELO", MODELO_POR_DEFECTO),
        "umbral": UMBRAL_POR_DEFECTO,
        "presupuesto_ms": LATENCIA_MAXIMA_MS,
    }
