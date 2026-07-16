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


def split_think_block(content: str) -> tuple[str, str]:
    """Split hybrid-reasoning output "thinking...</think>answer" → (reasoning, answer).

    Qwen3-family templates open <think> in the prompt scaffold, so the output
    contains the thinking followed by </think> and the final answer. Engines
    without a reasoning parser (GX10 vLLM opt-in thinking, MLX servers on M4)
    deliver that mixed in content. Returns ("", content) when no block found.
    """
    if "</think>" not in content:
        return "", content
    thinking, _, answer = content.rpartition("</think>")
    thinking = thinking.replace("<think>", "").strip()
    return thinking, answer.strip()


def sanitize_response_data(data: dict) -> dict:
    """Apply all sanitizations to a completion response dict (non-streaming)."""
    for choice in data.get("choices", []):
        msg = choice.get("message") or choice.get("delta") or {}
        # Reasoning field name varies by engine: litellm/Nemotron use
        # "reasoning_content"; vLLM ≥0.25 (GX10) emits "reasoning".
        reasoning = msg.pop("reasoning_content", None) or msg.pop("reasoning", None)
        msg.pop("thinking_blocks", None)
        # Inline think block (engine without reasoning parser): split it out
        # so clients always get a clean final answer in content.
        if isinstance(msg.get("content"), str) and "</think>" in msg["content"]:
            thinking, answer = split_think_block(msg["content"])
            if answer:
                msg["content"] = answer
                reasoning = reasoning or thinking
        # Reasoning models can exhaust max_tokens thinking and leave content
        # empty (finish=length before </think>). Fall back to the reasoning,
        # flagged, so the client sees the partial work instead of nothing.
        if not msg.get("content") and isinstance(reasoning, str) and reasoning.strip():
            msg["content"] = (
                "[razonamiento truncado — sube max_tokens o desactiva thinking]\n"
                + reasoning.strip()
            )
        if isinstance(msg.get("content"), str):
            msg["content"] = sanitize_tts_markup(msg["content"])
    return data


def sanitize_stream_chunk(chunk_data: dict) -> dict:
    """Apply per-chunk sanitization for streaming responses."""
    for choice in chunk_data.get("choices", []):
        delta = choice.get("delta") or {}
        delta.pop("reasoning_content", None)
        delta.pop("reasoning", None)
        delta.pop("thinking_blocks", None)
        if isinstance(delta.get("content"), str):
            delta["content"] = _TTS_BRACKET_RE.sub("", delta["content"])
    return chunk_data
