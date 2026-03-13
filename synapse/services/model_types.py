"""Model type classification based on model name patterns.

Classifies models into categories: language, image, audio, tts, embedding, moderation.
Used to filter non-LLM models from chat completions and routing.
"""

import re

MODEL_TYPE = "language"  # default

# Patterns checked in order — first match wins.
# Each tuple: (compiled regex, type string)
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Embeddings
    (re.compile(r"(text-embedding|embed|bge-|e5-|gte-|nomic-embed|mxbai-embed|snowflake-arctic-embed|all-minilm)", re.I), "embedding"),
    # Image generation
    (re.compile(r"(dall-e|stable-diffusion|sdxl|imagen-|flux|midjourney|kandinsky|playground-v)", re.I), "image"),
    # TTS / speech synthesis (only dedicated TTS models, not multimodal LLMs)
    (re.compile(r"(^tts-|elevenlabs|piper)", re.I), "tts"),
    # Audio / STT (only pure STT models, not multimodal LLMs with audio support)
    (re.compile(r"(^whisper)", re.I), "audio"),
    # Moderation
    (re.compile(r"(text-moderation|moderation-|omni-moderation)", re.I), "moderation"),
    # Rerankers
    (re.compile(r"(rerank|re-rank)", re.I), "rerank"),
]


def classify_model_type(model_name: str) -> str:
    """Classify a model name into a type category.

    Returns one of: language, image, tts, audio, embedding, moderation, rerank.
    Defaults to 'language' if no pattern matches.
    """
    for pattern, model_type in _PATTERNS:
        if pattern.search(model_name):
            return model_type
    return "language"


def classify_models(model_names: list[str]) -> dict[str, str]:
    """Classify a list of model names. Returns {model_name: type}."""
    return {name: classify_model_type(name) for name in model_names}


def filter_language_models(model_names: list[str]) -> list[str]:
    """Return only language (chat) models from a list."""
    return [name for name in model_names if classify_model_type(name) == "language"]
