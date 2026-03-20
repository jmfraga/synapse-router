"""OpenAI-compatible chat completions endpoint."""

import json
import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.database import get_db
from synapse.models import ApiKey, ApiKeySmartRoute, SmartRoute
from synapse.services.auth import authenticate
from synapse.services.router import router_engine

router = APIRouter()

# ---------------------------------------------------------------------------
# Sanitize hallucinated TTS / function_calls markup that some models inject
# ---------------------------------------------------------------------------
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


def sanitize_tts_markup(content: str) -> str:
    """Strip hallucinated TTS / function_calls markup from LLM responses."""
    if not content:
        return content
    # Replace TTS invoke blocks with just the extracted text
    content = _TTS_INVOKE_RE.sub(_extract_tts_text, content)
    # Remove remaining function_calls blocks (e.g. message/send)
    content = _FUNC_CALLS_RE.sub("", content)
    # Remove [[tts:...]] markers
    content = _TTS_BRACKET_RE.sub("", content)
    # Clean up excessive whitespace
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: Optional[str | list] = None


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    messages: list[Message]
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = False
    stop: Optional[list[str] | str] = None


@router.post("/v1/chat/completions")
async def chat_completions(
    request: CompletionRequest,
    api_key: ApiKey = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    # Check model access — smart routes assigned to this key are always allowed
    if api_key.allowed_models != "*":
        allowed = [m.strip() for m in api_key.allowed_models.split(",")]
        if request.model not in allowed:
            # Check if it's an assigned smart route name
            sr_check = await db.execute(
                select(ApiKeySmartRoute.smart_route_id)
                .join(SmartRoute, SmartRoute.id == ApiKeySmartRoute.smart_route_id)
                .where(
                    ApiKeySmartRoute.api_key_id == api_key.id,
                    SmartRoute.name == request.model,
                )
            )
            if not sr_check.scalar_one_or_none():
                raise HTTPException(403, f"Model '{request.model}' not allowed for this key")

    kwargs = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.stop is not None:
        kwargs["stop"] = request.stop
    # Forward select extra fields that providers support
    _BASE_FIELDS = {"model", "messages", "temperature", "max_tokens", "top_p", "stream", "stop"}
    _FORWARD_FIELDS = {
        "thinking", "reasoning", "response_format",
        "presence_penalty", "frequency_penalty", "logprobs",
        "top_logprobs", "n", "seed", "user",
    }
    for key, val in request.model_dump(exclude_none=True).items():
        if key in _FORWARD_FIELDS and key not in kwargs:
            kwargs[key] = val

    messages = [m.model_dump() for m in request.messages]

    if request.stream:
        return StreamingResponse(
            _stream_response(messages, request.model, db, api_key.id, **kwargs),
            media_type="text/event-stream",
        )

    try:
        response = await router_engine.complete(
            messages=messages,
            model=request.model,
            db=db,
            api_key_id=api_key.id,
            stream=False,
            **kwargs,
        )
    except Exception as e:
        logger.exception("completions error model=%s: %s", request.model, e)
        raise HTTPException(502, f"Provider error: {e}")
    data = response.model_dump()
    # Strip thinking/reasoning blocks — keep OpenAI-compatible format (text only)
    # Also sanitize hallucinated TTS/function_calls markup
    for choice in data.get("choices", []):
        msg = choice.get("message") or choice.get("delta") or {}
        msg.pop("reasoning_content", None)
        msg.pop("thinking_blocks", None)
        if isinstance(msg.get("content"), str):
            msg["content"] = sanitize_tts_markup(msg["content"])
    # Inject cost into usage so Arena and clients can read it
    if hasattr(response, "usage") and response.usage:
        try:
            import litellm
            cost = litellm.completion_cost(completion_response=response)
            if data.get("usage") is None:
                data["usage"] = {}
            data["usage"]["cost"] = cost
        except Exception as e:
            logger.warning("completion_cost failed model=%s: %s", request.model, e)
    return data


async def _stream_response(
    messages: list[dict],
    model: str,
    db: AsyncSession,
    api_key_id: int,
    **kwargs,
):
    """Stream SSE chunks from the provider."""
    try:
        response = await router_engine.complete(
            messages=messages,
            model=model,
            db=db,
            api_key_id=api_key_id,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            chunk_data = chunk.model_dump()
            for choice in chunk_data.get("choices", []):
                delta = choice.get("delta") or {}
                delta.pop("reasoning_content", None)
                delta.pop("thinking_blocks", None)
                # Best-effort per-chunk sanitization for single-line TTS markers
                if isinstance(delta.get("content"), str):
                    delta["content"] = _TTS_BRACKET_RE.sub("", delta["content"])
            yield f"data: {json.dumps(chunk_data)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        error = {"error": {"message": str(e), "type": "server_error"}}
        yield f"data: {json.dumps(error)}\n\n"
