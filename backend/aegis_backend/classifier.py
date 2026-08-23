from __future__ import annotations

import json
import re
import time

from .evidence import Evidence, fetch
from .store import Verdict

# Clasificar un dominio cuesta una llamada a un modelo. Se hace **una sola vez**
# por dominio en toda la red de clientes, asi que el costo es despreciable y la
# cobertura crece sola. Lo que no puede pasar es que el agente espere: la
# clasificacion es asincrona y el agente decide mientras tanto con su politica.

UMBRAL_IA = 0.6

# Senales en el nombre del dominio. Ordenan la cola y sirven de red cuando el
# sitio no responde, pero nunca deciden solas: hay negocios legitimos con "ai"
# en el nombre y servicios de IA que no lo tienen.
_TOKENS_FUERTES = (
    "gpt", "llm", "chatbot", "copilot", "openai", "anthropic", "claude",
    "gemini", "deepseek", "mistral", "perplexity", "huggingface",
)
_TOKENS_DEBILES = (
    "ai", "ia", "chat", "bot", "asistente", "assistant", "neural", "brain",
    "mind", "genius", "prompt", "smart",
)

# Lo que dice el sitio de si mismo. Esto si decide, porque un servicio de IA
# necesita explicarle al visitante que hace.
_FRASES_FUERTES = (
    "inteligencia artificial", "artificial intelligence", "language model",
    "modelo de lenguaje", "ai assistant", "asistente de ia", "ai chat",
    "chat con ia", "powered by gpt", "large language model", "ai agent",
    "genera con ia", "generate with ai", "ai-powered",
)
_FRASES_DEBILES = (
    "prompt", "chatbot", "gpt", "llm", "copilot", "resume tu", "summarize",
    "pregunta lo que", "ask anything", "escribe con", "write with",
)

_SEPARADORES = re.compile(r"[.\-_]")

# El titulo de una portada es corto y curado: si ahi aparece "AI" o "IA" suelto,
# el sitio se esta presentando como tal. En el cuerpo de la pagina la misma
# palabra aparece por cualquier motivo, asi que esta senal solo vale arriba.
_IA_EN_TITULO = re.compile(r"\b(?:a\.?i\.?|i\.?a\.?)\b", re.I)
_ASISTENTE = re.compile(
    r"\b(?:asistente (?:inteligente|virtual|de ia)|smart assistant"
    r"|ai (?:assistant|presentation|writer|video|search|notetaker|meeting"
    r"|agent|chat|tool|editor))\b",
    re.I,
)

# El titulo de una portada es corto y curado: si ahi dice "AI" o "IA" suelto, el
# sitio se esta presentando como tal. En el cuerpo de la pagina la misma palabra
# aparece por cualquier motivo, asi que esta senal solo vale en el titulo.
_IA_EN_TITULO = re.compile(r"\b(?:a\.?i\.?|i\.?a\.?)\b", re.I)
_ASISTENTE = re.compile(
    r"\b(?:asistente (?:inteligente|virtual|de ia)|smart assistant|ai (?:assistant|"
    r"presentation|writer|video|search|notetaker|meeting|agent|chat|tool))\b",
    re.I,
)


def _tokens(domain: str) -> list[str]:
    return [parte for parte in _SEPARADORES.split(domain.lower()) if parte]


def heuristic_score(domain: str) -> tuple[float, str]:
    partes = _tokens(domain)
    fuertes = [t for t in partes if any(token in t for token in _TOKENS_FUERTES)]
    debiles = [t for t in partes if t in _TOKENS_DEBILES]

    puntaje = min(1.0, 0.7 * len(fuertes) + 0.25 * len(debiles))
    if fuertes:
        motivo = f"El nombre contiene {', '.join(fuertes)}"
    else:
        if debiles:
            motivo = f"El nombre sugiere un servicio de IA ({', '.join(debiles)})"
        else:
            motivo = "El nombre no da senales de un servicio de IA"
    return puntaje, motivo


def content_score(evidencia: Evidence) -> tuple[float, str]:
    """Puntua lo que el sitio dice de si mismo en su portada."""

    if not evidencia.reachable:
        resultado = (0.0, "El sitio no respondio")
    else:
        encabezado = f"{evidencia.title} {evidencia.description}"
        texto = f"{encabezado} {evidencia.snippet}".lower()
        fuertes = [f for f in _FRASES_FUERTES if f in texto]
        debiles = [f for f in _FRASES_DEBILES if f in texto]

        puntaje = min(1.0, 0.5 * len(fuertes) + 0.15 * len(debiles))
        titular = ""
        if _IA_EN_TITULO.search(encabezado):
            puntaje += 0.5
            titular = "se anuncia como IA en su titulo"
        if _ASISTENTE.search(texto):
            puntaje += 0.5
            titular = titular or "se presenta como un asistente"
        puntaje = min(1.0, puntaje)

        if titular:
            motivo = f"El sitio {titular}"
        else:
            if fuertes:
                motivo = f"El sitio se describe con: {', '.join(fuertes[:3])}"
            else:
                if debiles:
                    motivo = f"El sitio menciona: {', '.join(debiles[:3])}"
                else:
                    motivo = "El sitio no se presenta como un servicio de IA"
        resultado = (puntaje, motivo)
    return resultado


_PROMPT = """Sos un clasificador de seguridad. Decidi si este dominio ofrece un
servicio de inteligencia artificial al que un empleado podria pegarle texto o
subirle archivos de la empresa.

Dominio: {domain}
{evidencia}

Es IA si el sitio ofrece un modelo de lenguaje, un asistente conversacional, un
generador de texto, un transcriptor, o cualquier funcion donde lo que el usuario
escribe o sube lo procesa un modelo. No es IA si es una tienda, un banco, un
medio, una herramienta interna o un sitio corporativo comun.

Responde SOLO con un JSON:
{{"es_ia": true|false, "tipo": "llm_chat|llm_api|ai_feature|non_ai",
"confianza": 0.0-1.0, "evidencia": "una frase corta en espanol"}}

No incluyas contenido del usuario en tu respuesta: solo estas viendo una pagina
publica."""


def classify(domain: str, ask_model=None, buscar_evidencia=fetch) -> Verdict:
    """Investiga un dominio y devuelve su veredicto.

    Tres fuentes, en orden de peso: lo que el modelo concluye viendo la portada,
    lo que la portada dice de si misma, y como se llama el dominio. La ultima es
    la mas debil y solo manda cuando el sitio no responde.
    """

    evidencia = buscar_evidencia(domain)
    puntaje_nombre, motivo_nombre = heuristic_score(domain)
    puntaje_sitio, motivo_sitio = content_score(evidencia)

    fuente = "heuristic"
    # El nombre pesa menos que el sitio: hay negocios legitimos con "ia" en el
    # nombre y servicios de IA que no lo tienen. Pero cuando el sitio no
    # responde es lo unico que queda, y un "chatgpt-libre.co" no merece el
    # beneficio de la duda.
    confianza = max(puntaje_sitio, puntaje_nombre * 0.9)
    razon = motivo_sitio if evidencia.reachable else motivo_nombre
    tipo = "llm_chat" if confianza >= UMBRAL_IA else "non_ai"

    if ask_model is not None:
        respuesta = _ask(ask_model, domain, evidencia)
        if respuesta is not None:
            fuente = "llm_classifier"
            tipo = respuesta.get("tipo", tipo)
            confianza = float(respuesta.get("confianza", confianza))
            razon = str(respuesta.get("evidencia", razon))[:200]
            if not respuesta.get("es_ia"):
                tipo = "non_ai"

    es_ia = tipo != "non_ai" and confianza >= UMBRAL_IA
    return Verdict(
        domain=domain.lower().strip("."),
        classification="ai_unapproved" if es_ia else "non_ai",
        kind=tipo,
        confidence=round(confianza, 2),
        evidence=razon,
        source=fuente,
        classified_at=time.time(),
    )


def _ask(ask_model, domain: str, evidencia: Evidence) -> dict | None:
    try:
        crudo = ask_model(
            _PROMPT.format(
                domain=domain,
                evidencia=evidencia.as_text() or "El sitio no respondio.",
            )
        )
        inicio = crudo.index("{")
        fin = crudo.rindex("}") + 1
        respuesta = json.loads(crudo[inicio:fin])
    except Exception:
        # Si el modelo falla, quedan el sitio y el nombre. Un backend a medias no
        # puede dejar sin veredicto a toda la red.
        respuesta = None
    return respuesta


def anthropic_model(max_tokens: int = 300):
    """Cliente real, solo si hay API key en el entorno. Si no, devuelve None.

    `max_tokens` por defecto alcanza para clasificar un dominio o escribir una
    leccion (un par de oraciones). Quien pide algo mas largo -como los insights
    del panel, que son varios items- pide su propio cliente con un limite mayor;
    la key se sigue leyendo del mismo lugar.
    """

    # No solo del entorno: ver secretos.py, poner ANTHROPIC_API_KEY como
    # variable de usuario le cambia la autenticacion a los CLI de IA de esa
    # maquina.
    from .secretos import cargar

    api_key = cargar("ANTHROPIC_API_KEY")
    if not api_key:
        cliente = None
    else:
        import urllib.request

        def cliente(prompt: str) -> str:
            cuerpo = json.dumps(
                {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                }
            ).encode()
            peticion = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=cuerpo,
                headers={
                    "content-type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(peticion, timeout=20) as respuesta:
                datos = json.loads(respuesta.read())
            return datos["content"][0]["text"]

    return cliente
