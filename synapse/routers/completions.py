"""OpenAI-compatible chat completions and model listing endpoints.

v2: powered by litellm.Router — no classifier, no Smart Routes.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import litellm
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import ApiKey, Provider
from synapse.services.auth import authenticate
from synapse.services.content_blocks import detect_provider_kind, normalize_messages
from synapse.services.litellm_router import get_router
from synapse.services.model_capabilities import audio_input_mode, capability_metadata
from synapse.services.sanitizers import sanitize_response_data, sanitize_stream_chunk

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# /v1/models — OpenAI-compatible model listing
# ---------------------------------------------------------------------------

_MODELS_CACHE: dict = {"ts": 0.0, "data": None}
_MODELS_TTL_S = 180


@router.get("/v1/models")
async def list_models(
    api_key: ApiKey = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    """Return available models in OpenAI-compatible format."""
    from synapse.routers.admin import _fetch_models_for_provider, _get_provider_key

    now_mono = time.monotonic()
    if _MODELS_CACHE["data"] is not None and now_mono - _MODELS_CACHE["ts"] < _MODELS_TTL_S:
        return _MODELS_CACHE["data"]

    settings = get_settings()
    result = await db.execute(
        select(Provider).where(Provider.is_enabled.is_(True)).order_by(Provider.priority)
    )
    providers = result.scalars().all()

    now = int(time.time())
    all_model_entries = []

    async def _gather_provider(provider: Provider):
        key = _get_provider_key(provider, settings)
        if not key and not provider.is_local:
            return []
        discovered = await _fetch_models_for_provider(provider, key, settings)
        config = json.loads(provider.config_json) if provider.config_json else {}
        custom = config.get("custom_models", [])
        enabled = config.get("enabled_models", [])
        all_models = sorted(set(discovered + custom))
        if enabled:
            enabled_set = set(enabled)
            all_models = [m for m in all_models if m in enabled_set]
        return [
            {
                "id": model_id,
                "object": "model",
                "created": now,
                "owned_by": provider.name,
                "metadata": capability_metadata(model_id),
            }
            for model_id in all_models
        ]

    results = await asyncio.gather(*[_gather_provider(p) for p in providers])
    for entries in results:
        all_model_entries.extend(entries)

    payload = {"object": "list", "data": all_model_entries}
    _MODELS_CACHE["data"] = payload
    _MODELS_CACHE["ts"] = now_mono
    return payload


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


# Fields to forward beyond the base set
_FORWARD_FIELDS = {
    "thinking", "reasoning", "response_format",
    "presence_penalty", "frequency_penalty", "logprobs",
    "top_logprobs", "n", "seed", "user",
    "tools", "tool_choice",
}


@router.post("/v1/chat/completions")
async def chat_completions(
    request: CompletionRequest,
    api_key: ApiKey = Depends(authenticate),
    db: AsyncSession = Depends(get_db),
):
    llm_router = get_router()

    # Check model access
    if api_key.allowed_models != "*":
        allowed = [m.strip() for m in api_key.allowed_models.split(",")]
        if request.model not in allowed:
            raise HTTPException(403, f"Model '{request.model}' not allowed for this key")

    # Translate provider:model (colon) to provider/model (slash) for Arena compat.
    # For MLX providers, the registered model_name is the bare model_id (no prefix),
    # so strip the "mlx:" / "mlx-heavy:" prefix to hit the correct Router entry.
    model = request.model
    _STRIP_PROVIDER_PREFIXES = ("mlx:", "mlx-heavy:", "nvidia:")
    if model.startswith(_STRIP_PROVIDER_PREFIXES):
        model = model.split(":", 1)[1]
    elif ":" in model and "/" not in model:
        model = model.replace(":", "/", 1)

    kwargs = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        kwargs["top_p"] = request.top_p
    if request.stop is not None:
        kwargs["stop"] = request.stop

    for key, val in request.model_dump(exclude_none=True).items():
        if key in _FORWARD_FIELDS and key not in kwargs:
            kwargs[key] = val

    # Anthropic Opus 4.7+ deprecated `temperature`; litellm drop_params doesn't catch it yet.
    if model.startswith(("anthropic/claude-opus-4-7", "anthropic/claude-opus-4-8", "anthropic/claude-opus-5")):
        kwargs.pop("temperature", None)

    messages = [m.model_dump() for m in request.messages]
    # Resolve where audio gets handled: per-request `audio_input` override >
    # per-key audio_policy > default transcribe. "native" only holds if the
    # target model actually accepts audio — otherwise fall back to whisper.
    requested_policy = (
        request.model_dump().get("audio_input")
        or getattr(api_key, "audio_policy", None)
        or "transcribe"
    )
    audio_mode = "transcribed"
    if requested_policy == "native" and audio_input_mode(model) == "native":
        audio_mode = "native"

    # normalize_messages does blocking I/O (remote image fetch, whisper transcribe)
    # — run off the event loop. Fast path: plain-string contents skip the hop.
    if any(isinstance(m.get("content"), list) for m in messages):
        try:
            messages = await asyncio.to_thread(
                normalize_messages, messages, detect_provider_kind(model),
                audio_mode=audio_mode,
            )
        except Exception as e:
            request_id = uuid.uuid4().hex[:12]
            logger.exception(
                "normalize error request_id=%s model=%s: %s", request_id, model, e
            )
            raise HTTPException(502, {"error": "attachment_processing_failed", "request_id": request_id})

    # Pass api_key_id in metadata for the usage callback
    kwargs["metadata"] = {"api_key_id": api_key.id}

    if request.stream:
        return StreamingResponse(
            _stream_response(llm_router, model, messages, **kwargs),
            media_type="text/event-stream",
        )

    try:
        response = await llm_router.acompletion(
            model=model,
            messages=messages,
            stream=False,
            **kwargs,
        )
    except Exception as e:
        request_id = uuid.uuid4().hex[:12]
        logger.exception("completions error request_id=%s model=%s: %s", request_id, model, e)
        raise HTTPException(502, {"error": "upstream_error", "request_id": request_id})

    data = response.model_dump()
    sanitize_response_data(data)

    # Inject cost into usage so Arena and clients can read it
    if hasattr(response, "usage") and response.usage:
        try:
            cost = litellm.completion_cost(completion_response=response)
            if data.get("usage") is None:
                data["usage"] = {}
            data["usage"]["cost"] = cost
        except Exception as e:
            logger.warning("completion_cost failed model=%s: %s", model, e)
    return data


async def _stream_response(llm_router, model: str, messages: list[dict], **kwargs):
    """Stream SSE chunks via litellm.Router."""
    try:
        response = await llm_router.acompletion(
            model=model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        async for chunk in response:
            chunk_data = chunk.model_dump()
            sanitize_stream_chunk(chunk_data)
            yield f"data: {json.dumps(chunk_data)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        request_id = uuid.uuid4().hex[:12]
        logger.exception("stream error request_id=%s model=%s: %s", request_id, model, e)
        error = {"error": {"message": "upstream_error", "type": "server_error", "request_id": request_id}}
        yield f"data: {json.dumps(error)}\n\n"
