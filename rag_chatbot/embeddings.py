from __future__ import annotations

from openai import OpenAI

from .config import RuntimeSettings, load_settings, require_openai_key


def embed_texts(
    texts: list[str],
    settings: RuntimeSettings | None = None,
) -> list[list[float]]:
    settings = settings or load_settings()
    require_openai_key(settings)
    if not texts:
        return []

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
        dimensions=settings.openai_embedding_dimensions,
    )
    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def embed_query(query: str, settings: RuntimeSettings | None = None) -> list[float]:
    return embed_texts([query], settings)[0]
