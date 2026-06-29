"""Tests for content_blocks normalization."""

import base64
import io

import pymupdf
import pytest

from synapse.services.content_blocks import (
    detect_provider_kind,
    normalize_messages,
    pdf_to_image_blocks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def two_page_pdf_b64() -> str:
    """Build a minimal 2-page PDF in memory and return as base64."""
    doc = pymupdf.open()
    for label in ("Page 1 hola", "Page 2 mundo"):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), label, fontsize=14)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.fixture
def small_png_b64() -> str:
    """Build a 4x4 PNG via pymupdf and return base64."""
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 4, 4))
    pix.clear_with(200)
    return base64.b64encode(pix.tobytes("png")).decode("ascii")


# ---------------------------------------------------------------------------
# detect_provider_kind
# ---------------------------------------------------------------------------

def test_detect_anthropic():
    assert detect_provider_kind("anthropic/claude-sonnet-4-20250514") == "anthropic"
    assert detect_provider_kind("anthropic:claude-opus-4-7") == "anthropic"


def test_detect_openai_default():
    assert detect_provider_kind("mlx-community/Qwen3.6-35B-A3B-4bit") == "openai"
    assert detect_provider_kind("groq/llama-3.3-70b") == "openai"
    assert detect_provider_kind("") == "openai"


def test_detect_gemini():
    # Gemini through litellm uses openai-compatible shape on our path.
    assert detect_provider_kind("gemini/gemini-2.5-pro") == "openai"


# ---------------------------------------------------------------------------
# pdf_to_image_blocks
# ---------------------------------------------------------------------------

def test_pdf_to_image_blocks_openai(two_page_pdf_b64):
    blocks = pdf_to_image_blocks(two_page_pdf_b64, target="openai")
    assert len(blocks) == 2
    for b in blocks:
        assert b["type"] == "image_url"
        assert b["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_pdf_to_image_blocks_anthropic(two_page_pdf_b64):
    blocks = pdf_to_image_blocks(two_page_pdf_b64, target="anthropic")
    assert len(blocks) == 2
    for b in blocks:
        assert b["type"] == "image"
        assert b["source"]["type"] == "base64"
        assert b["source"]["media_type"] == "image/jpeg"
        assert len(b["source"]["data"]) > 100


def test_pdf_max_pages_caps(two_page_pdf_b64):
    blocks = pdf_to_image_blocks(two_page_pdf_b64, max_pages=1, target="openai")
    assert len(blocks) == 1


# ---------------------------------------------------------------------------
# normalize_messages — image conversion
# ---------------------------------------------------------------------------

def test_anthropic_shape_canonicalized_to_openai(small_png_b64):
    """Client sends Anthropic-native image block → normalizer converts to OpenAI image_url
    (canonical form). Applies to BOTH targets — litellm handles the Anthropic translation."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "describe"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": small_png_b64},
            },
        ],
    }]
    for target in ("openai", "anthropic"):
        out = normalize_messages(messages, target)
        blocks = out[0]["content"]
        assert blocks[0] == {"type": "text", "text": "describe"}
        assert blocks[1]["type"] == "image_url", f"target={target}"
        assert blocks[1]["image_url"]["url"] == f"data:image/png;base64,{small_png_b64}"


def test_openai_image_url_passthrough(small_png_b64):
    """image_url stays image_url for both targets — canonical form."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "describe"},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{small_png_b64}"},
            },
        ],
    }]
    for target in ("openai", "anthropic"):
        out = normalize_messages(messages, target)
        blocks = out[0]["content"]
        assert blocks[1]["type"] == "image_url", f"target={target}"
        assert blocks[1]["image_url"]["url"].endswith(small_png_b64)


# ---------------------------------------------------------------------------
# normalize_messages — PDF document
# ---------------------------------------------------------------------------

def test_pdf_document_rasterized_for_both_targets(two_page_pdf_b64):
    """PDF documents are rasterized to OpenAI image_url for BOTH Anthropic and
    OpenAI targets. litellm 1.63.11 only accepts OpenAI-shape content; the
    `document` block type fails its validator, so we rasterize and let litellm
    forward image_url blocks (which it translates internally for Anthropic)."""
    doc_block = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": two_page_pdf_b64,
        },
    }
    messages = [{"role": "user", "content": [{"type": "text", "text": "resume"}, doc_block]}]
    for target in ("openai", "anthropic"):
        out = normalize_messages(messages, target, max_pdf_pages=5)
        content = out[0]["content"]
        # 1 text block + 2 pages
        assert len(content) == 3, f"target={target}"
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[2]["type"] == "image_url"


def test_unknown_document_mime_dropped():
    block = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/octet-stream", "data": "AAAA"},
    }
    messages = [{"role": "user", "content": [{"type": "text", "text": "x"}, block]}]
    out = normalize_messages(messages, "openai")
    # Unknown mime is dropped silently (with a log warning)
    assert len(out[0]["content"]) == 1
    assert out[0]["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# cache_control handling
# ---------------------------------------------------------------------------

def test_cache_control_preserved_for_anthropic():
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "long system", "cache_control": {"type": "ephemeral"}},
        ],
    }]
    out = normalize_messages(messages, "anthropic")
    assert out[0]["content"][0].get("cache_control") == {"type": "ephemeral"}


def test_cache_control_stripped_for_openai():
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "long system", "cache_control": {"type": "ephemeral"}},
        ],
    }]
    out = normalize_messages(messages, "openai")
    assert "cache_control" not in out[0]["content"][0]


# ---------------------------------------------------------------------------
# Pass-through cases
# ---------------------------------------------------------------------------

def test_plain_string_content_unchanged():
    messages = [{"role": "user", "content": "hola"}]
    out = normalize_messages(messages, "openai")
    assert out == messages


def test_idempotent_image(small_png_b64):
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{small_png_b64}"}},
        ],
    }]
    once = normalize_messages(messages, "openai")
    twice = normalize_messages(once, "openai")
    assert once == twice


def test_idempotent_pdf(two_page_pdf_b64):
    """After first pass PDF becomes image_url blocks; second pass leaves them alone."""
    messages = [{
        "role": "user",
        "content": [{
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": two_page_pdf_b64},
        }],
    }]
    for target in ("openai", "anthropic"):
        once = normalize_messages(messages, target)
        twice = normalize_messages(once, target)
        assert once == twice, f"target={target}"
