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

# Donde se van los BYTES de un archivo adjunto. No son chats y por eso no
# estaban, pero son el canal por el que sale un documento entero: cuando alguien
# arrastra un .xlsx a ChatGPT, el archivo va aca y no a chatgpt.com. Sin esto el
# embudo lo descartaba por non_ai (ver subidas.py).
UPLOAD_ENDPOINTS: frozenset[str] = frozenset(
    {
        "files.oaiusercontent.com",
        "cdn.oaistatic.com",
        "uploads.anthropic.com",
        "files.anthropic.com",
        "upload.googleapis.com",
        "push.clients6.google.com",
    }
)

# Pasarelas y proxies de LLM. Merecen su propia categoria porque por ahi pasa
# TODO el prompt, igual que por la API del proveedor, y no aparecen en ninguna
# lista de "aplicaciones de IA" porque no tienen interfaz.
GATEWAYS: frozenset[str] = frozenset(
    {
        "gateway.ai.cloudflare.com",
        "api.helicone.ai",
        "oai.helicone.ai",
        "api.portkey.ai",
        "api.langbase.com",
        "api.requesty.ai",
        "api.unify.ai",
        "litellm.local",
    }
)

# Transcripcion. Una reunion entera se va en un solo archivo de audio, y el audio
# es justo lo que el motor no puede leer todavia: el destino es lo unico que hay.
TRANSCRIPTION: frozenset[str] = frozenset(
    {
        "api.deepgram.com",
        "api.speechmatics.com",
        "api.rev.ai",
        "api.gladia.io",
        "api.hume.ai",
        "api.openai.com/v1/audio",
    }
)

# Bases vectoriales y memoria de agentes. Es el mismo dato de la empresa, pero
# subido para quedarse: un indice de documentos internos es una copia completa.
VECTOR_STORES: frozenset[str] = frozenset(
    {
        "api.pinecone.io",
        "api.weaviate.io",
        "cloud.qdrant.io",
        "api.voyageai.com",
        "api.jina.ai",
        "app.mem0.ai",
        "api.turbopuffer.com",
    }
)

# Traductores. El canal de fuga mas viejo y el que nadie mira: pegar un contrato
# entero para traducirlo es exactamente la misma fuga que pegarlo en un chat.
TRANSLATION: frozenset[str] = frozenset(
    {
        "translate.google.com",
        "translate.googleapis.com",
        "translate.yandex.com",
        "api-free.deepl.com",
        "api.deepl.com",
    }
)

# Agentes y herramientas que aparecieron despues de que se escribio el catalogo.
AGENTS_AND_TOOLS: frozenset[str] = frozenset(
    {
        "manus.im",
        "genspark.ai",
        "chat.z.ai",
        "gamma.app",
        "napkin.ai",
        "api.tavily.com",
        "api.exa.ai",
        "api.firecrawl.dev",
        "api.warp.dev",
        "api.raycast.com",
        "api.jetbrains.ai",
        "api.augmentcode.com",
        "api.zed.dev",
        "app.hex.tech",
    }
)

# APIs de modelo que faltaban. dashscope y volces son los dos proveedores chinos
# con mas trafico corporativo y no estaban.
MORE_MODEL_APIS: frozenset[str] = frozenset(
    {
        "dashscope.aliyuncs.com",
        "ark.cn-beijing.volces.com",
        "api.minimax.chat",
        "api.minimaxi.com",
        "api.siliconflow.cn",
        "open.bigmodel.cn",
        "api.stepfun.com",
        "api.moonshot.cn",
        "api.baichuan-ai.com",
    }
)

# Un host literal no alcanza cuando el proveedor tiene un host por REGION.
# bedrock-runtime.us-east-1 estaba en la lista y las otras diecinueve regiones
# no, asi que Bedrock estaba cubierto en un 5%. Vertex AI no estaba en absoluto.
#
# Los patrones se consultan solo cuando el catalogo literal no encontro nada, asi
# que no le cuestan nada al camino comun. Y son deliberadamente ESTRECHOS: un
# patron ancho sobre blob.core.windows.net convertiria el almacenamiento propio
# de la empresa en un destino de IA, que es peor que no verlo.
AI_HOST_PATTERNS: tuple[str, ...] = (
    r"^bedrock(?:-runtime|-agent-runtime)?\.[a-z0-9-]+\.amazonaws\.com$",
    r"^(?:[a-z0-9-]+-)?aiplatform\.googleapis\.com$",
    r"^[a-z0-9-]+\.openai\.azure\.com$",
    r"^[a-z0-9-]+\.cognitiveservices\.azure\.com$",
    r"^[a-z0-9-]+\.services\.ai\.azure\.com$",
    r"^chatgpt-[a-z0-9-]+\.blob\.core\.windows\.net$",
    r"^[a-z0-9-]+\.inference\.ai\.azure\.com$",
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
    UPLOAD_ENDPOINTS,
    GATEWAYS,
    TRANSCRIPTION,
    VECTOR_STORES,
    TRANSLATION,
    AGENTS_AND_TOOLS,
    MORE_MODEL_APIS,
    DEMO,
)

CATEGORIES: dict[str, frozenset[str]] = {
    "chat": CHAT_ASSISTANTS,
    "model_api": MODEL_APIS | MORE_MODEL_APIS,
    "code": CODE_ASSISTANTS,
    "writing": WRITING_AND_DOCS,
    "meetings": MEETINGS_AND_AUDIO,
    "media": IMAGE_AND_VIDEO,
    "platform": AI_PLATFORMS,
    "upload": UPLOAD_ENDPOINTS,
    "gateway": GATEWAYS,
    "transcription": TRANSCRIPTION,
    "vector_store": VECTOR_STORES,
    "translation": TRANSLATION,
    "agent": AGENTS_AND_TOOLS,
    "demo": DEMO,
}


def category_of(domain: str) -> str | None:
    match = None
    for name, domains in CATEGORIES.items():
        if match is None and domain in domains:
            match = name
    return match
