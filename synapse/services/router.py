"""Intelligent routing engine — decides which provider:model to use for each request."""

import json
import time
import logging
from typing import AsyncIterator

import httpx
import litellm
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.models import Route, Provider, UsageLog, SmartRoute, ApiKey, ApiKeySmartRoute
from synapse.services.classifier import classify_intent

logger = logging.getLogger("synapse.router")

# Disable litellm telemetry and reduce noise
litellm.telemetry = False
litellm.drop_params = True
litellm.modify_params = True  # auto-fix incompatible params (e.g. tool_choice without tools)
litellm.request_timeout = 120  # seconds — fallback faster on slow/stuck providers


class RouterEngine:
    def __init__(self):
        self._provider_latencies: dict[str, float] = {}

    async def resolve_route(
        self, model: str, db: AsyncSession,
        messages: list[dict] | None = None,
        api_key_id: int = 0,
    ) -> tuple[list[dict], str, str, SmartRoute | None]:
        """Find the best provider chain for a given model request.

        Returns (chain, smart_route_name, intent, smart_route_obj) where chain
        is an ordered list of {provider, model, base_url, api_key} dicts.
        """
        # 0. Direct provider routing — format "provider:model"
        #    Used by Arena to bypass routing and send directly to a specific provider
        if ":" in model:
            parts = model.split(":", 1)
            provider_name = parts[0]
            # Verify it's a known provider name
            stmt = select(Provider).where(
                Provider.name == provider_name, Provider.is_enabled.is_(True)
            )
            result = await db.execute(stmt)
            if result.scalar_one_or_none():
                chain = [{"provider": provider_name, "model": parts[1]}]
                return await self._resolve_chain(chain, db), "", "", None

        # 1. Check smart routes (intent-based routing)
        smart = await self._check_smart_route(model, messages, db, api_key_id)
        if smart is not None:
            chain, sr_name, intent, sr_obj = smart
            return chain, sr_name, intent, sr_obj

        # 1. Check explicit routes first
        stmt = (
            select(Route)
            .where(Route.is_enabled.is_(True))
            .order_by(Route.priority)
        )
        result = await db.execute(stmt)
        routes = result.scalars().all()

        for route in routes:
            if self._matches_pattern(model, route.model_pattern):
                chain = json.loads(route.provider_chain)
                # Use the provider from the chain but keep the original
                # requested model name (e.g. sonar* routes to perplexity
                # but preserves sonar-pro vs sonar-deep-research)
                for entry in chain:
                    entry["model"] = model
                return await self._resolve_chain(chain, db), "", "", None

        # 2. No explicit route — build dynamic chain based on provider priority
        return await self._build_dynamic_chain(model, db), "", "", None

    async def complete(
        self,
        messages: list[dict],
        model: str,
        db: AsyncSession,
        api_key_id: int = 0,
        stream: bool = False,
        **kwargs,
    ):
        """Route a completion request through the provider chain."""
        chain, sr_name, intent, sr_obj = await self.resolve_route(
            model, db, messages=messages, api_key_id=api_key_id
        )

        if not chain:
            raise ValueError(f"No available provider for model: {model}")

        last_error = None
        for i, target in enumerate(chain):
            try:
                start = time.monotonic()

                # Ollama: bypass litellm to handle thinking models properly
                if target["provider"].startswith("ollama"):
                    response = await self._call_ollama(target, messages, **kwargs)
                    elapsed_ms = int((time.monotonic() - start) * 1000)

                    await self._log_usage(
                        db=db, api_key_id=api_key_id,
                        provider=target["provider"], model=target["model"],
                        response=response, latency_ms=elapsed_ms,
                        status="success" if i == 0 else "fallback",
                        route_path=" -> ".join(
                            f"{t['provider']}/{t['model']}" for t in chain[: i + 1]
                        ),
                        stream=stream, smart_route_name=sr_name, intent=intent,
                    )
                    self._provider_latencies[target["provider"]] = elapsed_ms

                    if stream:
                        return self._wrap_as_stream(response)
                    return response

                # All other providers: use litellm
                litellm_model = self._to_litellm_model(target)
                # Strip tool_choice if no tools provided (causes Anthropic error)
                clean_kwargs = {k: v for k, v in kwargs.items()
                                if not (k == "tool_choice" and "tools" not in kwargs)}
                call_kwargs = {
                    "model": litellm_model,
                    "messages": messages,
                    "stream": stream,
                    **clean_kwargs,
                }
                if target.get("base_url"):
                    call_kwargs["api_base"] = target["base_url"]
                if target.get("api_key"):
                    call_kwargs["api_key"] = target["api_key"]

                response = await litellm.acompletion(**call_kwargs)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                # Log usage
                await self._log_usage(
                    db=db,
                    api_key_id=api_key_id,
                    provider=target["provider"],
                    model=target["model"],
                    response=response,
                    latency_ms=elapsed_ms,
                    status="success" if i == 0 else "fallback",
                    route_path=" -> ".join(
                        f"{t['provider']}/{t['model']}" for t in chain[: i + 1]
                    ),
                    stream=stream,
                    smart_route_name=sr_name,
                    intent=intent,
                )

                # Update provider latency tracking
                self._provider_latencies[target["provider"]] = elapsed_ms

                return response

            except Exception as e:
                last_error = e
                logger.warning(
                    f"Provider {target['provider']}/{target['model']} failed: {e}. "
                    f"Trying next in chain..."
                )
                # Log the failure
                await self._log_usage(
                    db=db,
                    api_key_id=api_key_id,
                    provider=target["provider"],
                    model=target["model"],
                    response=None,
                    latency_ms=0,
                    status="error",
                    route_path=f"{target['provider']}/{target['model']}",
                    stream=stream,
                    smart_route_name=sr_name,
                    intent=intent,
                )
                continue

        # Cross-layer fallback: if a smart route intent chain failed entirely,
        # try the default chain as last resort
        if sr_obj and intent != "default":
            logger.warning(
                f"All providers for intent '{intent}' failed in smart route "
                f"'{sr_name}'. Falling back to default chain."
            )
            default_chain = json.loads(sr_obj.default_chain_json)
            fallback_chain = await self._resolve_chain(default_chain, db)

            for i, target in enumerate(fallback_chain):
                try:
                    start = time.monotonic()

                    if target["provider"].startswith("ollama"):
                        response = await self._call_ollama(target, messages, **kwargs)
                    else:
                        litellm_model = self._to_litellm_model(target)
                        call_kwargs = {
                            "model": litellm_model,
                            "messages": messages,
                            "stream": stream,
                            **kwargs,
                        }
                        if target.get("base_url"):
                            call_kwargs["api_base"] = target["base_url"]
                        if target.get("api_key"):
                            call_kwargs["api_key"] = target["api_key"]
                        response = await litellm.acompletion(**call_kwargs)

                    elapsed_ms = int((time.monotonic() - start) * 1000)

                    await self._log_usage(
                        db=db,
                        api_key_id=api_key_id,
                        provider=target["provider"],
                        model=target["model"],
                        response=response,
                        latency_ms=elapsed_ms,
                        status="fallback",
                        route_path=f"{intent}(failed) -> default/{target['provider']}/{target['model']}",
                        stream=stream,
                        smart_route_name=sr_name,
                        intent="default",
                    )

                    self._provider_latencies[target["provider"]] = elapsed_ms

                    if stream and target["provider"].startswith("ollama"):
                        return self._wrap_as_stream(response)
                    return response

                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"Default fallback {target['provider']}/{target['model']} "
                        f"also failed: {e}"
                    )
                    await self._log_usage(
                        db=db,
                        api_key_id=api_key_id,
                        provider=target["provider"],
                        model=target["model"],
                        response=None,
                        latency_ms=0,
                        status="error",
                        route_path=f"default/{target['provider']}/{target['model']}",
                        stream=stream,
                        smart_route_name=sr_name,
                        intent="default",
                    )
                    continue

        raise last_error or ValueError("All providers in chain failed")

    async def _check_smart_route(
        self, model: str, messages: list[dict] | None, db: AsyncSession,
        api_key_id: int = 0,
    ) -> tuple[list[dict], str, str, SmartRoute | None] | None:
        """Check if the request should use a smart route.

        Priority:
          1. Key-specific: model name matches a SmartRoute.name assigned to this key
          2. Global: model matches SmartRoute.trigger_model
        Returns (chain, smart_route_name, intent, smart_route_obj) or None.
        """
        smart_route = None

        # 1. Check key-specific smart routes
        if api_key_id:
            # 1a. Match model name against assigned smart route names
            stmt = (
                select(SmartRoute)
                .join(ApiKeySmartRoute, SmartRoute.id == ApiKeySmartRoute.smart_route_id)
                .where(
                    ApiKeySmartRoute.api_key_id == api_key_id,
                    func.lower(SmartRoute.name) == model.lower(),
                    SmartRoute.is_enabled.is_(True),
                )
            )
            result = await db.execute(stmt)
            smart_route = result.scalar_one_or_none()
            if smart_route:
                logger.info(
                    f"Using key-assigned smart route '{smart_route.name}' "
                    f"(model='{model}')"
                )

            # 1b. Backward compat: if key has exactly ONE route assigned
            #     and model didn't match by name, use it as default
            if not smart_route:
                stmt = (
                    select(SmartRoute)
                    .join(ApiKeySmartRoute, SmartRoute.id == ApiKeySmartRoute.smart_route_id)
                    .where(
                        ApiKeySmartRoute.api_key_id == api_key_id,
                        SmartRoute.is_enabled.is_(True),
                    )
                )
                result = await db.execute(stmt)
                assigned = result.scalars().all()
                if len(assigned) == 1:
                    smart_route = assigned[0]
                    logger.info(
                        f"Using single assigned route '{smart_route.name}' "
                        f"for key (compat mode)"
                    )

        # 2. Fall back to global trigger match
        if not smart_route:
            stmt = select(SmartRoute).where(
                func.lower(SmartRoute.trigger_model) == model.lower(),
                SmartRoute.is_enabled.is_(True),
            )
            result = await db.execute(stmt)
            smart_route = result.scalar_one_or_none()

        if not smart_route:
            return None

        sr_name = smart_route.name

        # Extract the user message for classification
        user_message = ""
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content")
                    if isinstance(content, str) and content.strip():
                        user_message = content
                        break
                    elif isinstance(content, list):
                        # Multimodal: extract text parts
                        text_parts = [
                            p.get("text", "") for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        if text_parts:
                            user_message = " ".join(text_parts)
                            break
                    # content is None or empty — keep searching earlier messages

        if not user_message:
            logger.warning("Smart route triggered but no user message found, using default")
            default_chain = json.loads(smart_route.default_chain_json)
            return await self._resolve_chain(default_chain, db), sr_name, "default", smart_route

        intent_name, chain = await classify_intent(user_message, smart_route, db)
        logger.info(f"Smart route '{sr_name}': intent={intent_name}")
        return await self._resolve_chain(chain, db), sr_name, intent_name, smart_route

    async def _call_ollama(self, target: dict, messages: list[dict], **kwargs):
        """Call Ollama's native API directly, bypassing litellm.

        Litellm can't handle 'thinking' fields from models like gpt-oss,
        deepseek-r1, qwen3.5 — returns empty content. This calls Ollama's
        /api/chat endpoint directly and constructs a compatible response.
        """
        base_url = (target.get("base_url") or "http://localhost:11434").rstrip("/")
        # Sanitize messages for Ollama:
        # - Skip tool messages (unsupported role)
        # - Convert content arrays to strings
        # - Strip tool_calls from assistant messages
        clean_messages = []
        for m in messages:
            if m.get("role") == "tool":
                continue
            msg = dict(m)
            if isinstance(msg.get("content"), list):
                msg["content"] = " ".join(
                    p.get("text", "") for p in msg["content"]
                    if isinstance(p, dict) and p.get("type") == "text"
                ) or ""
            msg.pop("tool_calls", None)
            msg.pop("tool_call_id", None)
            clean_messages.append(msg)
        body = {
            "model": target["model"],
            "messages": clean_messages,
            "stream": False,
        }
        if "temperature" in kwargs:
            body.setdefault("options", {})["temperature"] = kwargs["temperature"]
        if "max_tokens" in kwargs:
            body.setdefault("options", {})["num_predict"] = kwargs["max_tokens"]
        if "top_p" in kwargs:
            body.setdefault("options", {})["top_p"] = kwargs["top_p"]
        if "stop" in kwargs:
            body["stop"] = kwargs["stop"]

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{base_url}/api/chat", json=body)
            if resp.status_code >= 400:
                logger.warning("Ollama %s/%s 400 response: %s messages_roles=%s",
                    target["provider"], target["model"], resp.text[:300],
                    [m.get("role") for m in messages])
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("message", {})
        content = msg.get("content", "")

        # Build litellm-compatible response
        return litellm.ModelResponse(
            id=f"chatcmpl-{int(time.time())}",
            model=f"ollama/{target['model']}",
            choices=[{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": (data.get("prompt_eval_count", 0) + data.get("eval_count", 0)),
            },
        )

    async def _wrap_as_stream(self, response):
        """Wrap a non-streaming response as an async generator of SSE-compatible chunks."""
        content = response.choices[0].message.content or ""
        chunk_data = {
            "id": response.id,
            "object": "chat.completion.chunk",
            "created": response.created,
            "model": response.model,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
        }
        from litellm import ModelResponse
        chunk = ModelResponse(**chunk_data, stream=True)
        yield chunk

    def _matches_pattern(self, model: str, pattern: str) -> bool:
        """Check if a model name matches a route pattern. Supports * wildcard."""
        if pattern == "*":
            return True
        if "*" in pattern:
            prefix = pattern.replace("*", "")
            return model.startswith(prefix)
        return model == pattern

    def _to_litellm_model(self, target: dict) -> str:
        """Convert our provider:model to litellm format."""
        provider = target["provider"]
        model = target["model"]

        provider_prefixes = {
            "ollama": "ollama/",
            "ollama-heavy": "ollama/",
            "anthropic": "anthropic/",
            "minimax": "anthropic/",
            "groq": "groq/",
            "nvidia": "nvidia_nim/",
            "openai": "",
            "gemini": "gemini/",
            "perplexity": "perplexity/",
        }
        prefix = provider_prefixes.get(provider, f"{provider}/")
        return f"{prefix}{model}"

    async def _resolve_chain(self, chain: list[dict], db: AsyncSession) -> list[dict]:
        """Resolve a chain config into full provider details."""
        resolved = []
        for entry in chain:
            provider_name = entry["provider"]
            stmt = select(Provider).where(
                Provider.name == provider_name, Provider.is_enabled.is_(True)
            )
            result = await db.execute(stmt)
            provider = result.scalar_one_or_none()
            if provider:
                resolved.append(
                    {
                        "provider": provider_name,
                        "model": entry["model"],
                        "base_url": provider.base_url or "",
                        "api_key": self._get_provider_key(provider),
                    }
                )
        return resolved

    async def _build_dynamic_chain(self, model: str, db: AsyncSession) -> list[dict]:
        """Build a fallback chain dynamically based on provider priority."""
        stmt = (
            select(Provider)
            .where(Provider.is_enabled.is_(True))
            .order_by(Provider.priority)
        )
        result = await db.execute(stmt)
        providers = result.scalars().all()

        chain = []
        for provider in providers:
            chain.append(
                {
                    "provider": provider.name,
                    "model": model,
                    "base_url": provider.base_url or "",
                    "api_key": self._get_provider_key(provider),
                }
            )
        return chain

    def _get_provider_key(self, provider: Provider) -> str:
        """Get API key for a provider. DB value takes priority over env var."""
        if provider.api_key_value:
            return provider.api_key_value
        if provider.api_key_env:
            import os
            return os.environ.get(provider.api_key_env, "")
        return ""

    async def _log_usage(
        self,
        db: AsyncSession,
        api_key_id: int,
        provider: str,
        model: str,
        response,
        latency_ms: int,
        status: str,
        route_path: str,
        stream: bool,
        smart_route_name: str = "",
        intent: str = "",
    ):
        """Log usage metrics to database."""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cost = 0.0

        if response and not stream and hasattr(response, "usage") and response.usage:
            prompt_tokens = response.usage.prompt_tokens or 0
            completion_tokens = response.usage.completion_tokens or 0
            total_tokens = response.usage.total_tokens or 0
            try:
                cost = litellm.completion_cost(completion_response=response)
            except Exception:
                pass

        log = UsageLog(
            api_key_id=api_key_id,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            cost_usd=cost,
            status=status,
            route_path=route_path,
            smart_route_name=smart_route_name,
            intent=intent,
        )
        db.add(log)
        await db.commit()


# Singleton
router_engine = RouterEngine()
