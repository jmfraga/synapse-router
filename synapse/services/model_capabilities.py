"""Model capability flags (vision, document support).

Used by /v1/models to enrich each entry with `metadata.supports_vision` and
`metadata.supports_documents`, so clients (Arena, future Phoenix/Iris UIs) can
filter the model dropdown when an image/PDF is attached.

Detection is by name pattern — there is no global registry of provider model
capabilities. Update VISION_PATTERNS / DOCUMENT_PATTERNS when a new vision or
document-capable model lands.
"""

import re
from typing import Iterable


# Patterns matched against the FULL model id as it appears in /v1/models
# (e.g. "anthropic:claude-sonnet-4-20250514", "mlx-community/Qwen3.6-35B-A3B-4bit").
# Case-insensitive substring match — keep patterns broad enough to survive
# minor version bumps (claude-sonnet-4-* etc.).
VISION_PATTERNS: tuple[str, ...] = (
    # Anthropic
    "claude-3-5-sonnet",
    "claude-3-7-sonnet",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-opus-5",
    # OpenAI
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "o1",
    "o3",
    "o4",
    # Google
    "gemini-2.0-flash",
    "gemini-2.5",
    "gemini-1.5",
    # NVIDIA NIM
    "llama-3.2-90b-vision",
    "llama-3.2-11b-vision",
    "vila",
    # Local MLX (Qwen-VL family on :8088, mlx_vlm)
    "qwen3-vl",
    "qwen3.6",  # mlx_vlm-served, accepts images
    "qwen2-vl",
    "qwen2.5-vl",
)

# Native document support (PDF as document block, not as images).
# Today only Anthropic has it natively via pdf_input/document blocks.
# Others receive PDFs as image arrays via the content_blocks normalizer.
DOCUMENT_PATTERNS: tuple[str, ...] = (
    "claude-3-5-sonnet",
    "claude-3-7-sonnet",
    "claude-sonnet-4",
    "claude-opus-4",
    "claude-opus-5",
)


def _matches_any(model_id: str, patterns: Iterable[str]) -> bool:
    m = model_id.lower()
    return any(p in m for p in patterns)


def supports_vision(model_id: str) -> bool:
    """True if the model can accept image inputs (image_url or Anthropic image block)."""
    return _matches_any(model_id, VISION_PATTERNS)


def supports_documents(model_id: str) -> bool:
    """True if the model natively accepts PDF/document blocks (no client-side rasterization needed)."""
    return _matches_any(model_id, DOCUMENT_PATTERNS)


def capability_metadata(model_id: str) -> dict:
    """Return the `metadata` dict to attach to a /v1/models entry."""
    return {
        "supports_vision": supports_vision(model_id),
        "supports_documents": supports_documents(model_id),
    }
