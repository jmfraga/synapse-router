"""Build and manage the litellm.Router instance from DB providers."""

import json
import logging
import os
import time

import litellm
from litellm import Router
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.models import Provider
from synapse.services.litellm_callback import SynapseUsageCallback

logger = logging.getLogger("synapse.litellm_router")

# Singleton — initialized at startup via build_router()
_router: Router | None = None
_last_reload: float = 0
_model_count: int = 0


def get_router() -> Router:
    """Get the initialized litellm Router. Raises if not yet built."""
    if _router is None:
        raise RuntimeError("litellm Router not initialized — call build_router() first")
    return _router


def get_router_status() -> dict:
    """Return current Router status for the admin dashboard."""
    if _router is None:
        return {"status": "not_initialized", "models": [], "last_reload": 0}

    models = []
    for entry in _router.model_list:
        params = entry.get("litellm_params", {})
        models.append({
            "model_name": entry.get("model_name", "?"),
            "litellm_model": params.get("model", "?"),
            "api_base": params.get("api_base", "default"),
            "has_key": bool(params.get("api_key")),
        })

    return {
        "status": "ok",
        "model_count": _model_count,
        "last_reload": _last_reload,
        "models": models,
    }


# Map Synapse provider names to litellm model prefixes
_PROVIDER_PREFIXES = {
    "ollama": "ollama/",
    "anthropic": "anthropic/",
    "groq": "groq/",
    "nvidia": "nvidia_nim/",
    "openai": "openai/",
    "gemini": "gemini/",
    "perplexity": "perplexity/",
}


async def build_router(db: AsyncSession) -> Router:
    """Build a litellm.Router from all enabled providers in the DB."""
    global _router

    result = await db.execute(
        select(Provider).where(Provider.is_enabled.is_(True)).order_by(Provider.priority)
    )
    providers = result.scalars().all()

    model_list = []

    for provider in providers:
        name = provider.name
        base_url = provider.base_url or ""
        api_key = _get_key(provider)
        config = json.loads(provider.config_json) if provider.config_json else {}

        if name.startswith("mlx"):
            # MLX: each model may have its own base URL
            model_urls = config.get("model_base_urls", {})
            enabled = config.get("enabled_models", [])
            custom = config.get("custom_models", [])
            all_models = list(set(enabled or custom))

            for model_id in all_models:
                model_base = model_urls.get(model_id, base_url).rstrip("/")
                if not model_base.endswith("/v1"):
                    model_base = f"{model_base}/v1"
                model_list.append({
                    "model_name": model_id,
                    "litellm_params": {
                        "model": f"openai/{model_id}",
                        "api_base": model_base,
                        "api_key": "not-needed",
                    },
                })
                logger.info("Added MLX model: %s -> %s", model_id, model_base)

        elif name == "minimax":
            # MiniMax: OpenAI-compatible endpoint
            model_list.append({
                "model_name": "minimax/*",
                "litellm_params": {
                    "model": "openai/*",
                    "api_base": "https://api.minimax.io/v1",
                    "api_key": api_key,
                },
            })

        elif name == "ollama":
            # Ollama: wildcard passthrough
            model_list.append({
                "model_name": "ollama/*",
                "litellm_params": {
                    "model": "ollama/*",
                    "api_base": base_url or "http://localhost:11434",
                },
            })

        else:
            # Cloud providers: use litellm native prefixes
            prefix = _PROVIDER_PREFIXES.get(name, f"{name}/")
            model_list.append({
                "model_name": f"{name}/*",
                "litellm_params": {
                    "model": f"{prefix}*",
                    "api_key": api_key,
                },
            })

        logger.info("Registered provider: %s", name)

    # Configure litellm globals
    litellm.telemetry = False
    litellm.drop_params = True
    litellm.modify_params = True
    litellm.request_timeout = 120

    # Register usage callback
    callback = SynapseUsageCallback()
    litellm.callbacks = [callback]

    _router = Router(
        model_list=model_list,
        num_retries=3,
        timeout=120,
        retry_after=5,
        allowed_fails=2,
        cooldown_time=60,
    )

    global _model_count, _last_reload
    _model_count = len(model_list)
    _last_reload = time.time()

    logger.info("litellm Router initialized with %d model entries", len(model_list))
    return _router


async def reload_router(db: AsyncSession) -> Router:
    """Rebuild the litellm Router from current DB state. Called after admin changes."""
    logger.info("Reloading litellm Router...")
    return await build_router(db)


def _get_key(provider: Provider) -> str:
    """Get API key: DB stored value > env var."""
    if provider.api_key_value:
        return provider.api_key_value
    if provider.api_key_env:
        return os.environ.get(provider.api_key_env, "")
    return ""
