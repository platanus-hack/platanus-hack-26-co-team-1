from __future__ import annotations

import os
import re
import time

from .store import Verdict

# Clasificar un dominio cuesta una llamada a un modelo. Se hace **una sola vez**
# por dominio en toda la red de clientes, asi que el costo es despreciable y la
# cobertura crece sola. Lo que no puede pasar es que el agente espere: la
# clasificacion es asincrona y el agente decide mientras tanto con su politica.

# Senales en el propio nombre del dominio. No alcanzan solas para condenar a un
# sitio, pero ordenan la cola de revision y sirven de red cuando no hay modelo.
_TOKENS_FUERTES = (
    "gpt", "llm", "chatbot", "copilot", "openai", "anthropic", "claude",
    "gemini", "deepseek", "mistral", "perplexity", "huggingface",
)
_TOKENS_DEBILES = (
    "ai", "ia", "chat", "bot", "asistente", "assistant", "neural", "brain",
    "mind", "genius", "prompt", "gen", "smart", "auto",
)

_SEPARADORES = re.compile(r"[.\-_]")


def _tokens(domain: str) -> list[str]:
    return [parte for parte in _SEPARADORES.split(domain.lower()) if parte]


def heuristic_score(domain: str) -> tuple[float, str]:
    """Puntaje por el nombre del dominio, sin red y sin modelo.

    Es deliberadamente conservador: prefiere no clasificar antes que clasificar
    mal, porque un veredicto equivocado se propaga a todos los clientes.
    """

    partes = _tokens(domain)
    fuertes = [t for t in partes if any(token in t for token in _TOKENS_FUERTES)]
    debiles = [t for t in partes if t in _TOKENS_DEBILES]

    puntaje = min(1.0, 0.6 * len(fuertes) + 0.25 * len(debiles))
    if fuertes:
        motivo = f"El nombre contiene {', '.join(fuertes)}"
    else:
        if debiles:
            motivo = f"El nombre sugiere un servicio de IA ({', '.join(debiles)})"
        else:
            motivo = "El nombre no da senales de un servicio de IA"
    return puntaje, motivo


_PROMPT = """Analiza el dominio {domain} y responde SOLO con un JSON:
{{"es_ia": true|false, "tipo": "llm_chat|llm_api|ai_feature|non_ai",
"confianza": 0.0-1.0, "evidencia": "una frase corta en espanol"}}

Es IA si el sitio ofrece un modelo de lenguaje, un asistente conversacional, o
una funcion donde el usuario pega texto o sube archivos que procesa un modelo.
No incluyas contenido del usuario en tu respuesta."""


def classify(domain: str, ask_model=None) -> Verdict:
    """Devuelve el veredicto de un dominio.

    ``ask_model`` recibe un prompt y devuelve texto; se inyecta para poder
    probar el flujo completo sin llamar a ninguna API.
    """

    puntaje, motivo = heuristic_score(domain)
    fuente = "heuristic"
    tipo = "llm_chat" if puntaje >= 0.6 else "non_ai"
    confianza = puntaje
    evidencia = motivo

    if ask_model is not None:
        respuesta = _ask(ask_model, domain)
        if respuesta is not None:
            fuente = "llm_classifier"
            tipo = respuesta.get("tipo", tipo)
            confianza = float(respuesta.get("confianza", confianza))
            evidencia = str(respuesta.get("evidencia", evidencia))[:200]
            if not respuesta.get("es_ia"):
                tipo = "non_ai"

    es_ia = tipo != "non_ai" and confianza >= 0.6
    return Verdict(
        domain=domain.lower().strip("."),
        classification="ai_unapproved" if es_ia else "non_ai",
        kind=tipo,
        confidence=round(confianza, 2),
        evidence=evidencia,
        source=fuente,
        classified_at=time.time(),
    )


def _ask(ask_model, domain: str) -> dict | None:
    import json

    try:
        crudo = ask_model(_PROMPT.format(domain=domain))
        inicio = crudo.index("{")
        fin = crudo.rindex("}") + 1
        respuesta = json.loads(crudo[inicio:fin])
    except Exception:
        # Si el modelo falla, queda la heuristica. Un backend caido no puede
        # dejar sin veredicto a toda la red.
        respuesta = None
    return respuesta


def anthropic_model():
    """Cliente real, solo si hay API key en el entorno. Si no, devuelve None."""

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        cliente = None
    else:
        import json
        import urllib.request

        def cliente(prompt: str) -> str:
            cuerpo = json.dumps(
                {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 300,
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
