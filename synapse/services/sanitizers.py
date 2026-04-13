"""Response sanitization — extracted from completions.py for reuse in v2 path."""

import re

# Hallucinated TTS / function_calls patterns
_TTS_INVOKE_RE = re.compile(
    r'<function_calls>\s*<invoke name="tts">.*?</invoke>\s*</function_calls>',
    re.DOTALL,
)
_FUNC_CALLS_RE = re.compile(r"<function_calls>.*?</function_calls>", re.DOTALL)
_TTS_BRACKET_RE = re.compile(r"\[\[tts:[^\]]*\]\]")


def _extract_tts_text(match: re.Match) -> str:
    """Pull the text parameter from a hallucinated TTS function_calls block."""
    text_m = re.search(
        r'<parameter name="text">(.*?)</parameter>', match.group(0), re.DOTALL
    )
    return text_m.group(1).strip() if text_m else ""


def sanitize_gpt_oss_channels(content: str) -> str:
    """Extract the 'final' channel from gpt-oss multi-channel output."""
    if "<|channel|>" not in content:
        return content
    m = re.search(
        r"<\|channel\|>final<\|message\|>(.*?)(?:<\|return\|>|<\|end\|>|$)",
        content,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip()
    channels = re.findall(
        r"<\|channel\|>(\w+)<\|message\|>(.*?)(?:<\|end\|>|<\|return\|>|$)",
        content,
        re.DOTALL,
    )
    if channels:
        _, last_content = channels[-1]
        cleaned = last_content.strip()
        if cleaned:
            return cleaned
    return re.sub(r"<\|[^|]+\|>", "", content).strip()


def sanitize_tts_markup(content: str) -> str:
    """Strip hallucinated TTS / function_calls markup from LLM responses."""
    if not content:
        return content
    content = sanitize_gpt_oss_channels(content)
    content = _TTS_INVOKE_RE.sub(_extract_tts_text, content)
    content = _FUNC_CALLS_RE.sub("", content)
    content = _TTS_BRACKET_RE.sub("", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content


def sanitize_response_data(data: dict) -> dict:
    """Apply all sanitizations to a completion response dict (non-streaming)."""
    for choice in data.get("choices", []):
        msg = choice.get("message") or choice.get("delta") or {}
        msg.pop("reasoning_content", None)
        msg.pop("thinking_blocks", None)
        if isinstance(msg.get("content"), str):
            msg["content"] = sanitize_tts_markup(msg["content"])
    return data


def sanitize_stream_chunk(chunk_data: dict) -> dict:
    """Apply per-chunk sanitization for streaming responses."""
    for choice in chunk_data.get("choices", []):
        delta = choice.get("delta") or {}
        delta.pop("reasoning_content", None)
        delta.pop("thinking_blocks", None)
        if isinstance(delta.get("content"), str):
            delta["content"] = _TTS_BRACKET_RE.sub("", delta["content"])
    return chunk_data
