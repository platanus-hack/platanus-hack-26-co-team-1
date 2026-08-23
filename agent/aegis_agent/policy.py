from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

Classification = Literal[
    "ai_approved", "ai_unapproved", "ai_unknown", "non_ai", "passthrough"
]
Action = Literal["allow", "warn", "block_destination", "block_content"]

from .catalog import AI_DOMAINS, AI_HOST_PATTERNS  # noqa: E402  (catalogo semilla)
from .detect.model import (  # noqa: E402
    ETIQUETAS_POR_DEFECTO,
    ETIQUETAS_PRECISAS,
    UMBRAL_POR_DEFECTO,
)
from .detect.types import ORIGEN_IMAGEN  # noqa: E402
from .suffixes import most_specific_match  # noqa: E402

# Dominios que no se descifran nunca, ni para inspeccionar. Ver ADR 0003.
PASSTHROUGH_DOMAINS: frozenset[str] = frozenset(
    {
        "bancolombia.com",
        "davivienda.com",
        "bbva.com.co",
        "gov.co",
        "sura.co",
        "windowsupdate.com",
        "microsoft.com",
        "mozilla.org",
    }
)


# Dos formas de tratar una IA no aprobada, y la eleccion es de la empresa:
#
#   estricto     se corta el destino. Nadie usa lo que no esta aprobado.
#   equilibrado  se deja usar, pero se inspecciona cada envio y no sale ni un
#                dato sensible. El uso queda igual registrado en el panel, asi
#                que la visibilidad del shadow AI no se pierde.
#
# El segundo es mas facil de sostener en una empresa real: bloquear la
# herramienta que la gente ya usa termina en excepciones, VPNs y telefonos
# personales, que es exactamente donde nadie ve nada.
MODOS: dict[str, str] = {"estricto": "block_destination", "equilibrado": "inspect"}
MODO_POR_DEFECTO = "equilibrado"


def _accion_para_no_aprobadas() -> str:
    modo = os.environ.get("AEGIS_MODO", MODO_POR_DEFECTO).strip().lower()
    return MODOS.get(modo, MODOS[MODO_POR_DEFECTO])


def modo_pedido_por_el_entorno() -> str | None:
    """La accion que pide AEGIS_MODO, o None si nadie la puso.

    Se distingue "no esta puesta" de "esta puesta en el valor por defecto"
    porque son cosas distintas: la primera deja mandar a la politica guardada y
    la segunda es una decision explicita de quien instalo el agente.

    Un valor que no es ningun modo tampoco es una decision, asi que devuelve
    None y manda la politica.
    """

    crudo = os.environ.get("AEGIS_MODO", "").strip().lower()
    return MODOS.get(crudo) if crudo else None


@dataclass(frozen=True)
class CustomRule:
    """Una regla de deteccion escrita por la empresa, no por nosotros.

    El patron viaja como texto y se compila recien en detect/ruleset.py: si la
    regex es invalida, la regla se descarta ahi sin tumbar al agente. Es una
    dataclass congelada para que Policy siga siendo hashable.
    """

    id: str
    pattern: str
    category: str = "internal_data"
    severity: str = "high"


# Los valores que el motor entiende. Cualquier otra cosa que llegue de la web
# se corrige al default en vez de propagarse: una severidad desconocida hace
# KeyError en el orden de severidad del engine.
_CATEGORIAS_VALIDAS = frozenset({"secret", "pii", "internal_data"})
_SEVERIDADES_VALIDAS = frozenset({"critical", "high", "medium", "low"})


@dataclass(frozen=True)
class Policy:
    """Politica de la empresa. En produccion llega del backend y se cachea en disco."""

    tenant_id: str = "acme"
    approved_ai: frozenset[str] = field(default_factory=lambda: frozenset({"claude.ai", "api.anthropic.com"}))
    # Que hacer cuando sale un dato sensible hacia un dominio que todavia no
    # esta clasificado (ver decide._decide_destino_desconocido). "warn" es el
    # default: registra y deja pasar, porque el valor de esta rama es
    # descubrir el destino para que Haiku lo investigue, no frenar el primer
    # envio. "block_content" lo trata con la misma autoridad que una IA
    # conocida. "allow" es la salida de emergencia: ni siquiera se paga el
    # barrido barato.
    unknown_domain_action: Action = "warn"
    unapproved_ai_action: str = field(default_factory=_accion_para_no_aprobadas)
    # Que hacer con lo que encuentra el modelo. Por defecto manda la categoria:
    # una contrasena o un dato de empresa cortan igual que si los hubiera visto
    # T1, pero un dato personal suelto (nombre, direccion) solo advierte, porque
    # ahi el costo de un falso positivo es mas alto que el de dejarlo pasar.
    # "warn" es la salida de emergencia completa para la empresa que no confia
    # en el modelo: con eso, absolutamente ningun hallazgo del modelo bloquea,
    # sin importar la categoria.
    model_action: str = field(
        default_factory=lambda: os.environ.get("AEGIS_T2_ACCION", "block")
    )
    # Que etiquetas del modelo tienen autoridad para cortar un envio. Las demas
    # avisan: quedan en el panel y alimentan la leccion, pero no frenan a nadie.
    # Se decide por etiqueta y no por categoria porque dos etiquetas del mismo
    # tipo de dato pueden medir muy distinto: "nombre de cliente" se equivoca en
    # 1 de 36 frases normales y "empresa" en 6, y las dos son internal_data.
    model_block_labels: frozenset[str] = field(
        default_factory=lambda: frozenset(ETIQUETAS_PRECISAS)
    )
    block_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"secret", "internal_data"})
    )
    warn_categories: frozenset[str] = field(default_factory=lambda: frozenset({"pii"}))
    # Version del criterio de arriba, pero solo para lo que encuentra el modelo:
    # con esto una empresa puede confiar mas o menos en T2 que en T1 sin tocar
    # como se tratan las reglas deterministas.
    model_block_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"secret", "internal_data"})
    )
    # Que etiquetas le pide la empresa al modelo y con que umbral de confianza.
    # Hoy son las medidas en detect/model.py, pero una empresa con sus propios
    # datos internos puede agregar o sacar etiquetas sin tocar codigo.
    model_labels: tuple[str, ...] = ETIQUETAS_POR_DEFECTO
    model_threshold: float = UMBRAL_POR_DEFECTO
    # Que puede hacer Aegis con cada aplicacion, por nombre de proceso. Solo
    # dos valores: "bloquear" (lo normal) y "observar" (registra todo y no corta
    # nada).
    #
    # Existe porque un agente de codigo leyendo un repositorio no es lo mismo que
    # una persona pegando en un chat, y merece un trato distinto. El caso que lo
    # motivo es real y le pasa a cualquiera: un desarrollador cuyo repositorio
    # tiene credenciales de prueba en los fixtures queda bloqueado por su propio
    # codigo, todo el dia.
    #
    # Lo que NO puede hacer esto es reducir la cobertura, que es lo que prohibe
    # el ADR 0002. Por eso la aplicacion desconocida no cae en ninguna regla y se
    # queda con la politica estricta: hay que nombrarla para aflojarla, nunca al
    # reves. Y esto NO le llega al detector, que sigue recibiendo texto y destino
    # y nada mas.
    app_actions: dict[str, str] = field(default_factory=dict)
    # El diccionario de la empresa: termino -> etiqueta. Lo que solo esta
    # empresa sabe que es suyo, y por lo tanto lo unico que ningun detector
    # generico puede tener. Ver detect/diccionario.py.
    #
    # Vive en la politica y no en el codigo porque es, literalmente, la lista
    # mas sensible que tiene la empresa: nombres de clientes, proyectos sin
    # anunciar, dominios internos. Se edita desde el panel y viaja como el resto
    # de la politica.
    company_terms: dict[str, str] = field(default_factory=dict)
    # Igual que con el modelo: la empresa decide cuanta autoridad le da a su
    # propia lista. Por defecto corta, porque un termino declarado es una
    # decision explicita y no una probabilidad.
    company_terms_action: str = "block"
    # Que hacer con un intento de inyeccion de prompt. Por defecto avisa: la
    # deteccion es heuristica, igual que la del modelo, y cortarle a alguien la
    # respuesta a mitad de una conversacion por una probabilidad es la forma mas
    # rapida de que desinstalen Aegis.
    #
    # "block" solo aplica al ENVIO. La respuesta no se corta nunca: cuando llega,
    # el modelo ya la genero, y dejar a la herramienta esperando un cuerpo que no
    # va a llegar rompe la sesion sin evitar nada.
    injection_action: str = "warn"
    # Si se lee el texto de las imagenes que salen del equipo.
    #
    # Apagado por defecto porque cuesta segundos y no milisegundos (ver
    # detect/ocr.py), asi que tiene que ser una decision de la empresa. Lo que
    # NO puede seguir siendo es una variable de entorno invisible: `ocr_action`
    # ya vive en el panel, y una pantalla que deja elegir que hacer con lo que
    # se encuentra en una imagen mientras la lectura esta apagada por otro lado
    # promete algo que no ocurre. Las dos preguntas se contestan en el mismo
    # lugar o ninguna sirve.
    #
    # AEGIS_OCR sigue funcionando como interruptor de desarrollo: manda
    # cualquiera de los dos que diga que si.
    ocr_enabled: bool = False
    # Que autoridad tiene lo que se leyo de una IMAGEN.
    #
    # Es la tercera deteccion probabilistica del sistema y hasta aca era la
    # unica sin freno: un hallazgo de OCR cortaba con la misma autoridad que una
    # llave de AWS con formato reconocido. No corresponde, y esta medido en
    # detect/ocr.py: el texto que sale de una imagen es aproximado
    # -`Verano2026Bogota` se leyo como `Verano2o26Bogota`- asi que un caracter
    # mal leido puede cortarle el envio a alguien sin que hubiera nada.
    #
    # Por defecto avisa, igual que el modelo y que la inyeccion. "block" le
    # devuelve la autoridad completa a la empresa que la quiera.
    ocr_action: str = "warn"
    # Que hacer cuando la capa D detecta un punto ciego (una app que no pasa
    # por el proxy). "warn" solo lo reporta; "block" corta la conexion. El
    # mecanismo que lee este campo lo construye otra tarea: aca solo se
    # declara y se serializa.
    blind_spot_action: str = "warn"
    # Dominios que se cortan siempre, sin mirar el contenido.
    #
    # `approved_ai` es una lista blanca y responde otra pregunta: "esto esta
    # aprobado". Una empresa que quiere prohibir deepseek.com no tiene como
    # decirlo sacandolo de una lista donde nunca estuvo. Por eso va aparte y no
    # como el complemento de la otra.
    #
    # Gana sobre todo lo demas, incluida una aplicacion en modo observar: es la
    # unica regla de la politica que expresa una prohibicion y no una gradacion.
    blocked_domains: frozenset[str] = field(default_factory=frozenset)
    # Que hacer con una regla concreta, por rule_id: "block", "warn" o "off".
    #
    # Las categorias (block_categories, warn_categories) siguen decidiendo por
    # defecto y esto las matiza de a una. Existe porque una empresa puede querer
    # que `email_address` no moleste sin bajar toda la categoria `pii`, que es lo
    # unico que podia hacer antes: la eleccion era todo o nada.
    rule_actions: dict[str, str] = field(default_factory=dict)
    # Excepciones por persona: user_id -> accion ("observar" o "bloquear").
    #
    # Mismo criterio que app_actions y por la misma razon del ADR 0004: hay que
    # NOMBRAR a alguien para aflojarle la politica, nunca al reves. Quien no este
    # en esta lista se queda con la politica estricta.
    user_actions: dict[str, str] = field(default_factory=dict)
    # Lo mismo por area. Se resuelve despues de la persona: lo mas especifico
    # gana, igual que en la resolucion de dominios.
    area_actions: dict[str, str] = field(default_factory=dict)
    # Las cuentas de la empresa en las herramientas que SI estan aprobadas.
    #
    # `approved_ai` dice "ChatGPT se puede usar" y no alcanza: la cuenta
    # personal gratuita del empleado viaja por el mismo dominio aprobado y es
    # justamente la que entrena con lo que le peguen. Esto declara CUALES
    # cuentas son de la empresa; lo que no este declarado es de otro.
    #
    # Son huellas y identificadores de organizacion, nunca credenciales: ver
    # identidad.py. Vacio significa apagado, porque con la lista vacia toda
    # cuenta seria ajena y el primer dia se bloquearia la empresa entera.
    corporate_accounts: frozenset[str] = field(default_factory=frozenset)
    # Que hacer cuando una herramienta aprobada se usa con una cuenta que no es
    # de la empresa. Por defecto avisa, igual que unknown_domain_action: el
    # valor de esta capa es primero VER cuanta gente esta entrando con su cuenta
    # personal, y esa respuesta suele bastar para que la empresa decida sola.
    #
    # "block" degrada el destino a no aprobado, con lo cual hereda todo lo que
    # la empresa ya decidio para una IA no aprobada (unapproved_ai_action) en
    # vez de inventar un camino nuevo.
    foreign_account_action: str = "warn"
    # --- lo que la empresa configura sobre QUE se detecta (rama nico) --------
    #
    # OJO CON LA DUPLICACION, que es real y esta resuelta en detect/ruleset.py:
    # `disabled_rules` dice lo mismo que `rule_actions[id] == "off"`, y
    # `forbidden_terms` lo mismo que `company_terms`. Se conservan las cuatro
    # porque las dos formas ya tienen tests y pantalla, pero el motor las
    # reconcilia en UN solo lugar al compilar: dos maneras de escribirlo, una
    # sola de decidirlo.
    # Reglas T1 que la empresa apago por id (por ejemplo "email_address" si
    # mandar correos a la IA es parte del trabajo). Tambien alcanza a los
    # hallazgos sinteticos (bulk_pii_export, archivo_critico); no toca lo que
    # encuentra el modelo, que tiene sus propias perillas arriba.
    disabled_rules: frozenset[str] = field(default_factory=frozenset)
    # Terminos literales que no pueden salir: el nombre del proyecto secreto,
    # el cliente que nadie puede nombrar. En la web esto es un textarea. La
    # accion no se configura por termino: todos comparten una categoria y la
    # categoria ya decide via block_categories/warn_categories.
    forbidden_terms: tuple[str, ...] = ()
    forbidden_terms_category: str = "internal_data"
    # Reglas regex escritas por la empresa. Mas poder que los terminos (y mas
    # riesgo): una regex invalida se descarta al compilar, no aca.
    custom_rules: tuple[CustomRule, ...] = ()

    def a_dict(self) -> dict[str, Any]:
        """Serializa la politica a tipos JSON, estable y diffeable.

        Los frozenset se ordenan al convertirlos a lista para que el archivo
        no cambie de una corrida a otra solo por el orden de iteracion.
        """

        return {
            "tenant_id": self.tenant_id,
            "approved_ai": sorted(self.approved_ai),
            "unknown_domain_action": self.unknown_domain_action,
            "unapproved_ai_action": self.unapproved_ai_action,
            "model_action": self.model_action,
            "model_block_categories": sorted(self.model_block_categories),
            "model_block_labels": sorted(self.model_block_labels),
            "block_categories": sorted(self.block_categories),
            "warn_categories": sorted(self.warn_categories),
            "model_labels": list(self.model_labels),
            "model_threshold": self.model_threshold,
            "injection_action": self.injection_action,
            "ocr_enabled": self.ocr_enabled,
            "ocr_action": self.ocr_action,
            "company_terms": dict(sorted(self.company_terms.items())),
            "company_terms_action": self.company_terms_action,
            "app_actions": dict(sorted(self.app_actions.items())),
            "blind_spot_action": self.blind_spot_action,
            "blocked_domains": sorted(self.blocked_domains),
            "rule_actions": dict(sorted(self.rule_actions.items())),
            "user_actions": dict(sorted(self.user_actions.items())),
            "area_actions": dict(sorted(self.area_actions.items())),
            "corporate_accounts": sorted(self.corporate_accounts),
            "foreign_account_action": self.foreign_account_action,
            "disabled_rules": sorted(self.disabled_rules),
            "forbidden_terms": list(self.forbidden_terms),
            "forbidden_terms_category": self.forbidden_terms_category,
            "custom_rules": [
                {
                    "id": regla.id,
                    "pattern": regla.pattern,
                    "category": regla.category,
                    "severity": regla.severity,
                }
                for regla in self.custom_rules
            ],
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, Any], base: "Policy | None" = None) -> "Policy":
        """Reconstruye la politica desde un dict, tolerante en ambas puntas.

        Una clave desconocida se ignora: una politica escrita por un backend mas
        nuevo no puede romper un agente viejo.

        Y `base` cubre el caso inverso, que es el peligroso. Sin ella, una clave
        AUSENTE cae al default del codigo, asi que un backend viejo (o un
        formulario que manda solo el campo que se toco) resetea en silencio todo
        lo que no nombro. En un producto de seguridad eso significa que la
        politica de la empresa cambia sin que nadie lo haya decidido: paso en
        vivo, un backend con codigo anterior devolvio una politica parcial y le
        devolvio el bloqueo a un equipo que estaba en modo observacion.

        Con `base`, lo que el dict no dice se conserva.
        """

        base = base if base is not None else cls()
        campos_frozenset = (
            "approved_ai",
            "model_block_categories",
            "model_block_labels",
            "block_categories",
            "warn_categories",
            "blocked_domains",
            "corporate_accounts",
            "disabled_rules",
        )
        campos_tupla = ("model_labels", "forbidden_terms")
        campos_dict = (
            "app_actions",
            "company_terms",
            "rule_actions",
            "user_actions",
            "area_actions",
        )
        campos_simples = (
            "tenant_id",
            "unknown_domain_action",
            "unapproved_ai_action",
            "model_action",
            "model_threshold",
            "injection_action",
            "company_terms_action",
            "blind_spot_action",
            "foreign_account_action",
            "ocr_action",
            "ocr_enabled",
            "forbidden_terms_category",
        )

        valores: dict[str, Any] = {}
        for campo in campos_simples:
            valores[campo] = datos.get(campo, getattr(base, campo))
        for campo in campos_frozenset:
            valores[campo] = (
                frozenset(datos[campo]) if campo in datos else getattr(base, campo)
            )
        for campo in campos_tupla:
            valores[campo] = (
                tuple(datos[campo]) if campo in datos else getattr(base, campo)
            )
        for campo in campos_dict:
            valores[campo] = (
                dict(datos[campo]) if campo in datos else dict(getattr(base, campo))
            )
        valores["custom_rules"] = _custom_rules_tolerantes(
            datos.get("custom_rules", ())
        )

        return cls(**valores)


def _custom_rules_tolerantes(entradas: Any) -> tuple[CustomRule, ...]:
    """Convierte lo que haya mandado la web en reglas utilizables.

    Una entrada rota se salta y una categoria o severidad que el motor no
    conoce se corrige al default: la politica la edita gente, y un formulario
    a medio guardar no puede dejar a la empresa sin proteccion.
    """

    reglas: list[CustomRule] = []
    if not isinstance(entradas, (list, tuple)):
        return ()
    for entrada in entradas:
        if isinstance(entrada, CustomRule):
            entrada = {
                "id": entrada.id,
                "pattern": entrada.pattern,
                "category": entrada.category,
                "severity": entrada.severity,
            }
        if not isinstance(entrada, dict):
            continue
        rule_id = entrada.get("id")
        patron = entrada.get("pattern")
        if not rule_id or not patron:
            continue
        categoria = entrada.get("category", "internal_data")
        if categoria not in _CATEGORIAS_VALIDAS:
            categoria = "internal_data"
        severidad = entrada.get("severity", "high")
        if severidad not in _SEVERIDADES_VALIDAS:
            severidad = "high"
        reglas.append(
            CustomRule(
                id=str(rule_id),
                pattern=str(patron),
                category=categoria,
                severity=severidad,
            )
        )
    return tuple(reglas)


# Un dominio que nadie clasifico todavia igual se delata por la forma del
# request. Es lo unico que cubre el shadow AI del que la lista negra aun no se
# entero, que es justamente el caso peligroso.
AI_PATH_HINTS: tuple[str, ...] = (
    "/chat",
    "/completion",
    "/complete",
    "/v1/messages",
    "/generate",
    ":generate",
    "/ask",
    "/prompt",
    "/conversation",
    "/inference",
    "/predict",
    "/assistant",
    "/embedding",
    "/transcri",
    "/converse",
    "/invocations",
    "/responses",
    "/agent",
    # El mercado hispanohablante nombra sus endpoints en espanol, y una lista
    # armada solo con nombres en ingles no ve el asistente interno de nadie.
    "/asistente",
    "/pregunta",
    "/consulta",
    "/resumen",
    "/resumir",
    "/traducir",
)

# Hay claves que solo aparecen en un request a un modelo y claves que aparecen en
# cualquier API. Pesarlas distinto es lo que separa detectar un asistente nuevo
# de bloquear el sistema de facturacion.
STRONG_BODY_HINTS: tuple[str, ...] = (
    '"messages"',
    '"prompt"',
    '"inputs"',
    '"contents"',
    '"anthropic_version"',
    '"max_tokens"',
    '"max_output_tokens"',
)

WEAK_BODY_HINTS: tuple[str, ...] = (
    '"model"',
    '"temperature"',
    '"stream"',
    '"top_p"',
    '"system"',
    '"completion"',
    '"parameters"',
)

HINT_THRESHOLD = 2
BODY_SAMPLE_CHARS = 4000


def looks_like_ai_api(path: str, text: str) -> bool:
    lowered = path.lower()
    if any(hint in lowered for hint in AI_PATH_HINTS):
        result = True
    else:
        sample = text[:BODY_SAMPLE_CHARS]
        score = sum(2 for hint in STRONG_BODY_HINTS if hint in sample)
        score += sum(1 for hint in WEAK_BODY_HINTS if hint in sample)
        result = score >= HINT_THRESHOLD
    return result


def _match_length(host: str, domains: frozenset[str]) -> int:
    """Longitud del dominio mas especifico que matchea, o 0 si ninguno.

    Se compara por especificidad y no por orden de lista porque las listas se
    solapan: microsoft.com esta en passthrough y copilot.microsoft.com es una IA.
    Con un simple "primero passthrough", Copilot pasaba libre.

    La comparacion camina el host de mas especifico a menos (ver
    suffixes.py): unos pocos lookups de hash, no un barrido de todo el
    conjunto. Es lo que permite que la lista negra crezca a miles de
    dominios sin que el costo por peticion se mueva.
    """

    match = most_specific_match(host, domains)
    return len(match) if match else 0


# Los patrones se compilan una vez. Cubren a los proveedores que tienen un host
# por REGION: bedrock-runtime.us-east-1 estaba en la lista literal y las otras
# diecinueve regiones no, asi que Bedrock estaba cubierto en un 5%.
_PATRONES = tuple(re.compile(p) for p in AI_HOST_PATTERNS)


def _match_patron(host: str) -> int:
    """Largo del host si algun patron de IA lo reconoce, o 0.

    Se devuelve el largo y no un booleano para que compita en la misma escala que
    _match_length: la resolucion por especificidad tiene que seguir funcionando
    igual, y un host que matchea un patron es tan especifico como su propio
    nombre.
    """

    normalizado = host.lower().strip(".")
    return len(normalizado) if any(p.match(normalizado) for p in _PATRONES) else 0


def classify(host: str, policy: Policy) -> Classification:
    approved = _match_length(host, policy.approved_ai)
    catalogued = _match_length(host, AI_DOMAINS)
    # Solo si la lista literal no dijo nada. Es el camino comun --el 97% del
    # trafico no va a ninguna IA-- y no tiene por que pagar siete regex.
    if catalogued == 0:
        catalogued = _match_patron(host)
    exempt = _match_length(host, PASSTHROUGH_DOMAINS)

    if approved >= max(catalogued, exempt) and approved > 0:
        classification: Classification = "ai_approved"
    else:
        if catalogued >= exempt and catalogued > 0:
            classification = "ai_unapproved"
        else:
            if exempt > 0:
                classification = "passthrough"
            else:
                classification = "non_ai"
    return classification


def _decide_destino_desconocido(categories: set[str], policy: Policy) -> Action:
    """Que hacer con lo que sale hacia un dominio que todavia no se sabe si es IA.

    Sin hallazgos no hay nada que decidir: pasa igual que hoy, sin importar el
    modo. Con hallazgos, la autoridad la da unknown_domain_action: "warn"
    (el default) registra y deja pasar porque el valor de esta rama es
    descubrir el destino, no cortar el primer envio; "block_content" lo trata
    igual que a una IA conocida, con las mismas categorias; "allow" es la
    salida de emergencia que reproduce el embudo de siempre.
    """

    modo = policy.unknown_domain_action
    if not categories or modo == "allow":
        action: Action = "allow"
    else:
        if modo == "block_content":
            action = _por_categoria(categories, policy)
        else:
            action = "warn"
    return action


def _por_categoria(categories: set[str], policy: Policy) -> Action:
    """Que hacer con un contenido, mirando SOLO lo que se encontro adentro.

    Es la escalera de siempre --bloquear, avisar, dejar pasar-- y estaba escrita
    dos veces en este mismo archivo: una para el destino desconocido y otra para
    la IA conocida. Que el nucleo de la decision del producto estuviera copiado
    significa que cambiar la politica en un lado y no en el otro daba dos
    respuestas distintas para el mismo contenido, segun a donde iba.
    """

    if categories & policy.block_categories:
        action: Action = "block_content"
    else:
        if categories & policy.warn_categories:
            action = "warn"
        else:
            action = "allow"
    return action


def decide(classification: Classification, categories: set[str], policy: Policy) -> Action:
    """Cruza el destino con lo que se encontro en el contenido.

    El orden importa: el destino manda. Un dominio de IA no aprobada se corta
    aunque el contenido venga limpio, porque el problema ahi es el shadow AI, no
    el dato. Y en una IA aprobada no se corta el destino nunca: se corta el dato,
    que es lo que permite que la gente siga trabajando con la herramienta.
    """

    if classification == "passthrough":
        action: Action = "allow"
    else:
        if classification == "non_ai":
            action = _decide_destino_desconocido(categories, policy)
        else:
            if classification == "ai_unapproved" and policy.unapproved_ai_action == "block_destination":
                action = "block_destination"
            else:
                action = _por_categoria(categories, policy)
    return action


# Los dos unicos modos por aplicacion. "observar" registra todo y no corta nada.
OBSERVAR = "observar"
BLOQUEAR = "bloquear"


def modo_de_la_app(proceso: str, policy: Policy) -> str:
    """Que puede hacer Aegis con esta aplicacion.

    Una aplicacion que nadie nombro se queda con lo estricto. Es la unica forma
    de que esto no reduzca la cobertura: hay que nombrar una app para aflojarla,
    nunca al reves, asi que la herramienta de IA que el equipo de seguridad no
    sabe que existe sigue tratada como lo que es.
    """

    return policy.app_actions.get((proceso or "").lower(), BLOQUEAR)


def modo_de_la_persona(usuario: str, area: str, policy: Policy) -> str:
    """Si a esta persona -o a su area- se le aflojo la politica.

    Lo mas especifico gana: una excepcion nombrando a alguien pesa mas que una
    que nombra a su area entera, igual que en la resolucion de dominios.

    Y como en el ADR 0004: hay que NOMBRAR para aflojar, nunca al reves. Quien
    no aparezca en ninguna de las dos listas se queda con la politica estricta,
    asi que agregar un area no puede desproteger a nadie por accidente.
    """

    propia = policy.user_actions.get((usuario or "").strip().lower())
    del_area = policy.area_actions.get((area or "").strip().lower())
    return propia or del_area or BLOQUEAR


def decidir_sobre(
    classification: Classification,
    findings: list,
    policy: Policy,
    proceso: str = "",
    usuario: str = "",
    area: str = "",
    host: str = "",
) -> Action:
    """La decision completa, incluida la rebaja de autoridad del modelo.

    Vive aca y no en el addon porque el banco de pruebas tiene que medir lo
    mismo que hace el proxy. Un banco que mide otra cosa es peor que no tener
    banco: reporta en verde una configuracion que en produccion corta lo que no
    debe, o al reves, reporta ocho bloqueos falsos que nunca ocurrieron.

    La rebaja: lo que ve el modelo no bloquea a ciegas. Una contrasena o un dato
    de empresa cortan igual que si los hubiera visto T1; todo lo demas advierte,
    porque un hallazgo probabilistico no puede frenar a nadie con la misma
    autoridad que una llave de AWS con formato reconocido.
    """

    from .detect.model import etiqueta_de

    categorias = {hallazgo.category for hallazgo in findings}
    action = decide(classification, categorias, policy)
    peor = findings[0] if findings else None

    # Un dominio prohibido corta antes que nada y no lo rebaja nadie: es la
    # unica regla de la politica que expresa una prohibicion y no una gradacion.
    # Si una excepcion por persona pudiera aflojarlo, prohibir no significaria
    # nada.
    prohibido = _dominio_prohibido(host, policy)

    # La regla concreta matiza a su categoria. "off" apaga solo esa regla, que
    # es lo que permite callar `email_address` sin bajar toda la categoria pii.
    if peor is not None and not prohibido:
        por_regla = policy.rule_actions.get(peor.rule_id)
        if por_regla == "off":
            action = "allow"
        else:
            if por_regla in ("block", "warn"):
                action = "block_content" if por_regla == "block" else "warn"

    # La aplicacion puede rebajar un corte a un aviso, nunca al reves: el evento
    # se registra igual y la empresa lo ve en el panel. Va antes que la rebaja
    # del modelo porque una vez que quedo en "warn" ya no hay nada que rebajar.
    if action == "block_content" and modo_de_la_app(proceso, policy) == OBSERVAR:
        action = "warn"

    # Y lo mismo por persona o por area: rebaja un corte a un aviso, nunca al
    # reves. El evento se registra igual y la empresa lo sigue viendo.
    if action == "block_content" and modo_de_la_persona(usuario, area, policy) == OBSERVAR:
        action = "warn"

    # El diccionario es de la empresa: si ella misma prefiere solo enterarse, se
    # le hace caso. Va antes que la rebaja del modelo porque son excluyentes.
    if (
        peor is not None
        and action == "block_content"
        and peor.rule_id.startswith("empresa_")
        and policy.company_terms_action == "warn"
    ):
        action = "warn"

    # Lo leido de una imagen se rebaja por el mismo motivo que lo del modelo: es
    # probabilistico. Va antes de la rebaja del modelo y no despues porque son
    # excluyentes -- scan_model corre sobre el texto principal, nunca sobre una
    # vista de OCR -- y asi cada una se lee sin tener que pensar en la otra.
    if (
        peor is not None
        and action == "block_content"
        and peor.origen == ORIGEN_IMAGEN
        and policy.ocr_action != "block"
    ):
        action = "warn"

    if peor is not None and action == "block_content" and peor.rule_id.startswith("modelo:"):
        if policy.model_action == "warn":
            # Interruptor general: la empresa no confia en el modelo y ningun
            # hallazgo suyo bloquea, sin importar la categoria.
            action = "warn"
        else:
            autorizada = (
                peor.category in policy.model_block_categories
                and etiqueta_de(peor.rule_id) in policy.model_block_labels
            )
            if not autorizada:
                action = "warn"

    if prohibido:
        action = "block_content"
    return action


def _dominio_prohibido(host: str, policy: Policy) -> bool:
    """Si el destino esta en la lista de prohibidos, mirando tambien el dominio padre.

    Prohibir "deepseek.com" tiene que alcanzar para cortar
    "chat.deepseek.com": nadie va a enumerar los subdominios de un servicio que
    justamente no quiere usar.
    """

    limpio = (host or "").strip().lower().rstrip(".")
    prohibido = False
    for dominio in policy.blocked_domains:
        if limpio == dominio or limpio.endswith("." + dominio):
            prohibido = True
    return prohibido
