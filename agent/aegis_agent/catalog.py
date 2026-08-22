from __future__ import annotations

# Semilla de la base colaborativa. Ninguna lista alcanza sola: existen miles de
# servicios con un modelo detras y aparecen varios por semana. Por eso la lista
# es el piso y no el techo, y lo que cubre el resto es looks_like_ai_api.
#
# Agrupada por categoria porque el riesgo no es solo el chat: un transcriptor de
# reuniones o un "resumidor" de PDFs se lleva tanta informacion como ChatGPT, y
# nadie los tiene en el radar.

CHAT_ASSISTANTS: frozenset[str] = frozenset(
    {
        "chatgpt.com",
        "chat.openai.com",
        "claude.ai",
        "gemini.google.com",
        "bard.google.com",
        "copilot.microsoft.com",
        "chat.deepseek.com",
        "chat.mistral.ai",
        "grok.com",
        "x.ai",
        "perplexity.ai",
        "poe.com",
        "character.ai",
        "you.com",
        "chat.qwen.ai",
        "kimi.moonshot.cn",
        "yiyan.baidu.com",
        "chatglm.cn",
        "pi.ai",
        "meta.ai",
        "copilot.cloud.microsoft",
        "duckduckgo.com/aichat",
    }
)

MODEL_APIS: frozenset[str] = frozenset(
    {
        "api.openai.com",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        "api.deepseek.com",
        "api.mistral.ai",
        "api.cohere.ai",
        "api.cohere.com",
        "api.together.xyz",
        "api.groq.com",
        "openrouter.ai",
        "api.deepinfra.com",
        "api.fireworks.ai",
        "api.replicate.com",
        "api-inference.huggingface.co",
        "api.perplexity.ai",
        "api.x.ai",
        "api.novita.ai",
        "api.hyperbolic.xyz",
        "api.sambanova.ai",
        "api.cerebras.ai",
        "api.lepton.ai",
        "api.anyscale.com",
        "bedrock-runtime.us-east-1.amazonaws.com",
        "openai.azure.com",
    }
)

CODE_ASSISTANTS: frozenset[str] = frozenset(
    {
        "cursor.com",
        "api2.cursor.sh",
        "codeium.com",
        "windsurf.com",
        "tabnine.com",
        "api.tabnine.com",
        "copilot-proxy.githubusercontent.com",
        "api.githubcopilot.com",
        "sourcegraph.com",
        "app.codium.ai",
        "blackbox.ai",
        "phind.com",
        "v0.dev",
        "bolt.new",
        "lovable.dev",
        "replit.com",
    }
)

WRITING_AND_DOCS: frozenset[str] = frozenset(
    {
        "notion.so",
        "notebooklm.google.com",
        "jasper.ai",
        "copy.ai",
        "writesonic.com",
        "rytr.me",
        "quillbot.com",
        "grammarly.com",
        "deepl.com",
        "chatpdf.com",
        "askyourpdf.com",
        "humata.ai",
        "chatdoc.com",
        "sider.ai",
        "monica.im",
        "merlin.foyer.work",
    }
)

MEETINGS_AND_AUDIO: frozenset[str] = frozenset(
    {
        "otter.ai",
        "fireflies.ai",
        "read.ai",
        "tldv.io",
        "grain.com",
        "avoma.com",
        "gong.io",
        "elevenlabs.io",
        "api.elevenlabs.io",
        "api.assemblyai.com",
        "descript.com",
    }
)

IMAGE_AND_VIDEO: frozenset[str] = frozenset(
    {
        "midjourney.com",
        "leonardo.ai",
        "runwayml.com",
        "pika.art",
        "stability.ai",
        "api.stability.ai",
        "ideogram.ai",
        "civitai.com",
        "clipdrop.co",
        "heygen.com",
        "synthesia.io",
        "luma-ai.com",
    }
)

AI_PLATFORMS: frozenset[str] = frozenset(
    {
        "huggingface.co",
        "colab.research.google.com",
        "kaggle.com",
        "wandb.ai",
        "langsmith.com",
        "smith.langchain.com",
        "flowiseai.com",
        "dify.ai",
        "coze.com",
    }
)

# Dominios de la demo, para poder mostrar el flujo sin depender de un tercero.
DEMO: frozenset[str] = frozenset({"novaai.local", "asistente-ia.co"})

AI_DOMAINS: frozenset[str] = frozenset().union(
    CHAT_ASSISTANTS,
    MODEL_APIS,
    CODE_ASSISTANTS,
    WRITING_AND_DOCS,
    MEETINGS_AND_AUDIO,
    IMAGE_AND_VIDEO,
    AI_PLATFORMS,
    DEMO,
)

CATEGORIES: dict[str, frozenset[str]] = {
    "chat": CHAT_ASSISTANTS,
    "model_api": MODEL_APIS,
    "code": CODE_ASSISTANTS,
    "writing": WRITING_AND_DOCS,
    "meetings": MEETINGS_AND_AUDIO,
    "media": IMAGE_AND_VIDEO,
    "platform": AI_PLATFORMS,
    "demo": DEMO,
}


def category_of(domain: str) -> str | None:
    match = None
    for name, domains in CATEGORIES.items():
        if match is None and domain in domains:
            match = name
    return match
