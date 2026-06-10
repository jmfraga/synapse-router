"""OpenAI-compatible chat completions and model listing endpoints.

v2: powered by litellm.Router — no classifier, no Smart Routes.
"""

import asyncio
import json
import logging
import time
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
from synapse.services.litellm_router import get_router
from synapse.services.sanitizers import sanitize_response_data, sanitize_stream_chunk

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# /v1/models — OpenAI-compatible model listing
# ---------------------------------------------------------------------------

@router.get("/v1/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    """Return available models in OpenAI-compatible format."""
    from synapse.routers.admin import _fetch_models_for_provider, _get_provider_key

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
            }
            for model_id in all_models
        ]

    results = await asyncio.gather(*[_gather_provider(p) for p in providers])
    for entries in results:
        all_model_entries.extend(entries)

    return {"object": "list", "data": all_model_entries}


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

    messages = [m.model_dump() for m in request.messages]

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
        logger.exception("completions error model=%s: %s", model, e)
        raise HTTPException(502, f"Provider error: {e}")

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
        error = {"error": {"message": str(e), "type": "server_error"}}
        yield f"data: {json.dumps(error)}\n\n"
