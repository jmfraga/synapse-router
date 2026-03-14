"""Intelligent routing engine — decides which provider:model to use for each request."""

import json
import time
import logging
from typing import AsyncIterator

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.models import Route, Provider, UsageLog, SmartRoute, ApiKey
from synapse.services.classifier import classify_intent

logger = logging.getLogger("synapse.router")

# Disable litellm telemetry and reduce noise
litellm.telemetry = False
litellm.drop_params = True


class RouterEngine:
    def __init__(self):
        self._provider_latencies: dict[str, float] = {}

    async def resolve_route(
        self, model: str, db: AsyncSession,
        messages: list[dict] | None = None,
        api_key_id: int = 0,
    ) -> tuple[list[dict], str, str]:
        """Find the best provider chain for a given model request.

        Returns (chain, smart_route_name, intent) where chain is an ordered
        list of {provider, model, base_url, api_key} dicts.
        """
        # 0. Check smart routes (intent-based routing)
        smart = await self._check_smart_route(model, messages, db, api_key_id)
        if smart is not None:
            chain, sr_name, intent = smart
            return chain, sr_name, intent

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
                return await self._resolve_chain(chain, db), "", ""

        # 2. No explicit route — build dynamic chain based on provider priority
        return await self._build_dynamic_chain(model, db), "", ""

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
        chain, sr_name, intent = await self.resolve_route(
            model, db, messages=messages, api_key_id=api_key_id
        )

        if not chain:
            raise ValueError(f"No available provider for model: {model}")

        last_error = None
        for i, target in enumerate(chain):
            try:
                start = time.monotonic()

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

        raise last_error or ValueError("All providers in chain failed")

    async def _check_smart_route(
        self, model: str, messages: list[dict] | None, db: AsyncSession,
        api_key_id: int = 0,
    ) -> tuple[list[dict], str, str] | None:
        """Check if the request should use a smart route.

        Priority: key-specific smart route > global trigger match.
        Returns (chain, smart_route_name, intent) or None.
        """
        smart_route = None

        # 1. Check if this API key has a dedicated smart route
        if api_key_id:
            key = await db.get(ApiKey, api_key_id)
            if key and key.smart_route_id:
                sr = await db.get(SmartRoute, key.smart_route_id)
                if sr and sr.is_enabled:
                    smart_route = sr
                    logger.info(
                        f"Using key-specific smart route '{sr.name}' "
                        f"for key '{key.name}'"
                    )

        # 2. Fall back to global trigger match
        if not smart_route:
            stmt = select(SmartRoute).where(
                SmartRoute.trigger_model == model,
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
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        user_message = content
                    break

        if not user_message:
            logger.warning("Smart route triggered but no user message found, using default")
            default_chain = json.loads(smart_route.default_chain_json)
            return await self._resolve_chain(default_chain, db), sr_name, "default"

        intent_name, chain = await classify_intent(user_message, smart_route, db)
        logger.info(f"Smart route '{sr_name}': intent={intent_name}")
        return await self._resolve_chain(chain, db), sr_name, intent_name

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
            "anthropic": "anthropic/",
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
