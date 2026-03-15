"""OpenAI-compatible chat completions endpoint."""

import json
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.database import get_db
from synapse.models import ApiKey, ApiKeySmartRoute, SmartRoute
from synapse.services.auth import authenticate
from synapse.services.router import router_engine

router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
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

    messages = [m.model_dump() for m in request.messages]

    if request.stream:
        return StreamingResponse(
            _stream_response(messages, request.model, db, api_key.id, **kwargs),
            media_type="text/event-stream",
        )

    response = await router_engine.complete(
        messages=messages,
        model=request.model,
        db=db,
        api_key_id=api_key.id,
        stream=False,
        **kwargs,
    )
    return response.model_dump()


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
            data = json.dumps(chunk.model_dump())
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        error = {"error": {"message": str(e), "type": "server_error"}}
        yield f"data: {json.dumps(error)}\n\n"
