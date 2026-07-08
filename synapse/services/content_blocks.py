"""Content-block normalization across providers.

Translates a single OpenAI/Anthropic-shaped `messages` payload into the format
the target provider expects, so a client can send one canonical shape and
Synapse routes it anywhere.

Today: image blocks (both directions), PDF documents (rasterized to images),
plain-text documents (TXT/MD/CSV spliced as text), and audio (`input_audio`
blocks transcribed server-side via the local whisper-server so ANY chat model
can consume audio through the gateway).

To add a new document type (DOCX, XLSX) later: register a handler in
DOCUMENT_HANDLERS keyed by mime_type. Each handler returns the list of
content blocks to splice in.

NOTE: this module performs blocking I/O (remote image fetch, whisper HTTP call).
Callers in async context must run normalize_messages via asyncio.to_thread.
"""

import base64
import io
import logging
import os
from typing import Callable, Literal

import httpx

logger = logging.getLogger(__name__)

ProviderKind = Literal["anthropic", "openai", "google"]

# Hard cap on PDF pages rendered to images for non-Anthropic providers.
# Keeps a single Arena battle bounded in cost/context.
PDF_MAX_PAGES_DEFAULT = 20
PDF_DPI_DEFAULT = 150
PDF_JPEG_QUALITY = 80

# Plain-text documents (TXT/MD/CSV) spliced inline — cap to keep one request
# bounded in context/cost. ~200k chars ≈ 50k tokens.
TEXT_DOC_MAX_CHARS = 200_000

# Local whisper-server used to transcribe input_audio blocks at the gateway.
# Same server audio.py uses for /v1/audio/transcriptions.
WHISPER_SERVER_URL = os.environ.get("SYNAPSE_WHISPER_URL", "http://localhost:8178")
AUDIO_TRANSCRIBE_TIMEOUT_S = 120.0


def detect_provider_kind(model: str) -> ProviderKind:
    """Map a model id to the wire format it expects.

    `model` may be "anthropic/claude-sonnet-4-...", "gemini/gemini-2.5-pro",
    or a bare local id like "mlx-community/Qwen3.6-...". Default openai-compat.
    """
    m = (model or "").lower()
    if m.startswith("anthropic/") or m.startswith("anthropic:"):
        return "anthropic"
    if m.startswith("gemini/") or m.startswith("gemini:") or m.startswith("google/"):
        # litellm gemini path actually uses google generative format,
        # but in litellm.acompletion it accepts OpenAI-style image_url —
        # treat as "openai" for content-block shape.
        return "openai"
    return "openai"


# ---------------------------------------------------------------------------
# PDF → image blocks (PyMuPDF)
# ---------------------------------------------------------------------------

def pdf_to_image_blocks(
    pdf_b64: str,
    *,
    max_pages: int = PDF_MAX_PAGES_DEFAULT,
    dpi: int = PDF_DPI_DEFAULT,
    target: ProviderKind = "openai",
) -> list[dict]:
    """Render a base64-encoded PDF into a list of image content blocks.

    For OpenAI-compatible providers each page becomes an image_url block with
    a data: URI. For Anthropic each page becomes a {type:"image", source:base64}
    block (used as fallback when caller explicitly wants images, not document).
    """
    try:
        import pymupdf  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency missing
        raise RuntimeError("pymupdf not installed; cannot rasterize PDF") from e

    raw = base64.b64decode(pdf_b64)
    doc = pymupdf.open(stream=raw, filetype="pdf")
    n = min(doc.page_count, max_pages)
    if doc.page_count > max_pages:
        logger.warning(
            "pdf_to_image_blocks: truncating PDF from %d to %d pages",
            doc.page_count, max_pages,
        )

    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    blocks: list[dict] = []
    for i in range(n):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        jpeg = pix.tobytes("jpeg", jpg_quality=PDF_JPEG_QUALITY)
        b64 = base64.b64encode(jpeg).decode("ascii")
        if target == "anthropic":
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })
        else:
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
    doc.close()
    return blocks


# Registry of document handlers by mime type. Each handler receives
# (data_b64, target_kind, opts) and returns content blocks to splice in.
# Register new types (docx, txt, md, xlsx) here as they're implemented.
DocumentHandler = Callable[[str, ProviderKind, dict], list[dict]]


def _handle_pdf(data_b64: str, target: ProviderKind, opts: dict) -> list[dict]:
    # Always render to OpenAI-shape image_url blocks — litellm handles the
    # Anthropic translation for us. Sending Anthropic-shape directly fails
    # litellm's OpenAI validator.
    return pdf_to_image_blocks(
        data_b64,
        max_pages=opts.get("max_pdf_pages", PDF_MAX_PAGES_DEFAULT),
        dpi=opts.get("pdf_dpi", PDF_DPI_DEFAULT),
        target="openai",
    )


def _handle_text_document(data_b64: str, target: ProviderKind, opts: dict) -> list[dict]:
    """Decode a plain-text family document and splice it as a text block.

    Works for ANY model — no vision requirement. Truncates at TEXT_DOC_MAX_CHARS.
    """
    try:
        text = base64.b64decode(data_b64).decode("utf-8", errors="replace")
    except Exception:
        logger.warning("content_blocks: failed to decode text document — dropping block")
        return []
    max_chars = opts.get("text_doc_max_chars", TEXT_DOC_MAX_CHARS)
    if len(text) > max_chars:
        logger.warning(
            "content_blocks: truncating text document from %d to %d chars",
            len(text), max_chars,
        )
        text = text[:max_chars] + "\n[... documento truncado ...]"
    return [{"type": "text", "text": f"[Documento adjunto]\n{text}"}]


DOCUMENT_HANDLERS: dict[str, DocumentHandler] = {
    "application/pdf": _handle_pdf,
    "text/plain": _handle_text_document,
    "text/markdown": _handle_text_document,
    "text/csv": _handle_text_document,
    "application/json": _handle_text_document,
    "text/x-markdown": _handle_text_document,
    # Future:
    #   "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _handle_docx,
    #   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _handle_xlsx,
}


# ---------------------------------------------------------------------------
# Audio: input_audio blocks → transcript text (whisper-server local)
# ---------------------------------------------------------------------------

def transcribe_audio_b64(data_b64: str, *, audio_format: str = "wav", language: str = "es") -> str:
    """Transcribe base64 audio via the local whisper-server. Returns the text.

    Raises RuntimeError if the whisper-server is unavailable or errors, so the
    caller surfaces a 502 instead of silently sending the prompt without audio.
    """
    raw = base64.b64decode(data_b64)
    filename = f"audio.{audio_format or 'wav'}"
    try:
        with httpx.Client(timeout=AUDIO_TRANSCRIBE_TIMEOUT_S) as client:
            resp = client.post(
                f"{WHISPER_SERVER_URL}/inference",
                files={"file": (filename, raw, f"audio/{audio_format or 'wav'}")},
                data={"response_format": "json", "language": language},
            )
    except httpx.HTTPError as e:
        raise RuntimeError(f"whisper-server unavailable: {e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"whisper-server error {resp.status_code}: {resp.text[:200]}")
    try:
        return (resp.json().get("text") or "").strip()
    except Exception as e:
        raise RuntimeError("whisper-server returned invalid JSON") from e


def _extract_audio(block: dict) -> tuple[str, str]:
    """Return (data_b64, format) from an OpenAI input_audio block or the
    defensive {type:"audio", source:{data, media_type}} variant."""
    if block.get("type") == "input_audio":
        ia = block.get("input_audio") or {}
        return ia.get("data", ""), ia.get("format", "wav")
    if block.get("type") == "audio":
        src = block.get("source") or {}
        media_type = src.get("media_type", "audio/wav")
        return src.get("data", ""), media_type.split("/")[-1]
    return "", "wav"


def _handle_audio_block(block: dict, audio_mode: str = "transcribed") -> list[dict]:
    """Normalize an audio block according to the resolved audio mode.

    "transcribed" (default): transcribe at the gateway via whisper and splice
    the transcript as text — universal, any chat model takes voice notes.
    "native": pass the audio through as a canonical OpenAI input_audio block —
    the model hears prosody/tone/intent. The caller must have verified the
    target model actually supports native audio (model_capabilities.audio_input_mode).
    """
    data_b64, audio_format = _extract_audio(block)
    if not data_b64:
        logger.warning("content_blocks: empty audio block — dropping")
        return []
    if audio_mode == "native":
        return [{"type": "input_audio", "input_audio": {"data": data_b64, "format": audio_format}}]
    transcript = transcribe_audio_b64(data_b64, audio_format=audio_format)
    if not transcript:
        return [{"type": "text", "text": "[Audio adjunto sin contenido transcribible]"}]
    return [{"type": "text", "text": f"[Transcripción del audio adjunto]\n{transcript}"}]


# ---------------------------------------------------------------------------
# Image block conversion (Anthropic ↔ OpenAI shapes)
# ---------------------------------------------------------------------------

def _url_to_b64(url: str, *, timeout: float = 10.0) -> tuple[str, str]:
    """Fetch an http(s) image URL and return (base64, media_type)."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        media_type = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        return base64.b64encode(r.content).decode("ascii"), media_type


def _to_anthropic_image(block: dict) -> dict:
    """Convert any image-shaped block to Anthropic's {type:"image", source:...} form."""
    if block.get("type") == "image" and isinstance(block.get("source"), dict):
        return block  # already anthropic
    # OpenAI image_url
    if block.get("type") == "image_url":
        url = (block.get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            # data:<mime>;base64,<payload>
            head, _, payload = url.partition(",")
            media_type = head.split(";")[0].removeprefix("data:") or "image/jpeg"
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": payload},
            }
        # remote URL → fetch
        b64, mt = _url_to_b64(url)
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": b64},
        }
    return block


def _to_openai_image(block: dict) -> dict:
    """Convert any image-shaped block to OpenAI's {type:"image_url", image_url:{url}} form."""
    if block.get("type") == "image_url":
        return block  # already openai
    if block.get("type") == "image" and isinstance(block.get("source"), dict):
        src = block["source"]
        if src.get("type") == "base64":
            media_type = src.get("media_type", "image/jpeg")
            data = src.get("data", "")
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            }
        if src.get("type") == "url":
            return {"type": "image_url", "image_url": {"url": src.get("url", "")}}
    return block


# ---------------------------------------------------------------------------
# Top-level message normalization
# ---------------------------------------------------------------------------

def _normalize_block(
    block: dict,
    target: ProviderKind,
    opts: dict,
) -> list[dict]:
    """Normalize a single content block; may expand to multiple (e.g. PDF → N images).

    Canonical shape inside Synapse is OpenAI. litellm receives OpenAI-shape and
    handles the Anthropic-native translation itself (sending `type=image` directly
    fails litellm's OpenAI validator — observed 2026-06-28).
    """
    btype = block.get("type")

    # Images: always canonicalize to OpenAI image_url regardless of target.
    if btype in ("image", "image_url"):
        return [_to_openai_image(block)]

    # Audio: transcribe at the gateway (default) or pass through natively
    # when the resolved audio_mode is "native" (prosody-aware models).
    if btype in ("input_audio", "audio"):
        return _handle_audio_block(block, opts.get("audio_mode", "transcribed"))

    # Document blocks: dispatch by mime_type
    if btype == "document":
        source = block.get("source") or {}
        media_type = source.get("media_type", "application/pdf")
        data_b64 = source.get("data", "")
        # Anthropic native: rasterize PDF and send as image_url blocks (canonical),
        # which litellm forwards to Anthropic as image content. Native `document`
        # blocks aren't supported by litellm 1.63.11's OpenAI-shape validator.
        if not data_b64:
            return []
        handler = DOCUMENT_HANDLERS.get(media_type)
        if handler is None:
            logger.warning(
                "content_blocks: no handler for document mime_type=%s — dropping block",
                media_type,
            )
            return []
        return handler(data_b64, target, opts)

    # Text / unknown blocks pass through
    return [block]


def _strip_cache_control(block: dict) -> dict:
    """Remove cache_control fields (Anthropic-specific) before sending to a non-Anthropic provider."""
    if "cache_control" in block:
        new_block = {k: v for k, v in block.items() if k != "cache_control"}
        return new_block
    return block


def normalize_messages(
    messages: list[dict],
    kind: ProviderKind,
    *,
    max_pdf_pages: int = PDF_MAX_PAGES_DEFAULT,
    pdf_dpi: int = PDF_DPI_DEFAULT,
    audio_mode: str = "transcribed",
) -> list[dict]:
    """Normalize a chat-completions `messages` payload for a target provider.

    Idempotent: normalizing twice yields the same result. Plain-string
    content is returned unchanged. Block lists are walked, images converted
    to the target shape, PDF document blocks rasterized for non-Anthropic
    providers, cache_control stripped when destination isn't Anthropic.
    audio_mode: "transcribed" (whisper at the gateway) or "native" (pass
    input_audio upstream — caller verified the model supports it).
    """
    opts = {"max_pdf_pages": max_pdf_pages, "pdf_dpi": pdf_dpi, "audio_mode": audio_mode}
    out: list[dict] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            out.append(msg)
            continue
        new_content: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                new_content.append(block)
                continue
            for normalized in _normalize_block(block, kind, opts):
                if kind != "anthropic":
                    normalized = _strip_cache_control(normalized)
                new_content.append(normalized)
        new_msg = dict(msg)
        new_msg["content"] = new_content
        out.append(new_msg)
    return out
