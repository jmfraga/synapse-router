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
from synapse.models.smart_route import SmartRoute
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
                # Sticky fallback: cualquier deployment MLX local (host 127.0.0.1
                # o localhost en cualquier puerto :80xx) recibe allowed_fails=3 /
                # cooldown_time=600. Origen: zombie-loop de Qwen3.6 (2026-05-04, 8
                # caídas en 80 min) por bugs upstream mlx-lm 0.31.2 en arquitecturas
                # híbridas + retry storm desde RPi5. Generalizado para cubrir Gemma-E4B
                # (8086), Qwen3.6 (8088) y Gemma-26B/31B (8091). Audio (:8090) no pasa
                # por el router. Detección por host evita falsos positivos contra
                # cloud providers.
                deployment = {
                    "model_name": model_id,
                    "litellm_params": {
                        "model": f"openai/{model_id}",
                        "api_base": model_base,
                        "api_key": "not-needed",
                    },
                }
                if ("//localhost:" in model_base) or ("//127.0.0.1:" in model_base):
                    deployment["litellm_params"]["allowed_fails"] = 3
                    deployment["litellm_params"]["cooldown_time"] = 600
                model_list.append(deployment)
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

        elif name == "nvidia":
            # NVIDIA NIM exposes models under vendor prefixes (z-ai/*, minimaxai/*,
            # google/*, meta/*, nvidia/*). Register one wildcard per known prefix
            # so clients can pass the vendor-prefixed model id directly.
            prefix = _PROVIDER_PREFIXES[name]  # "nvidia_nim/"
            nim_vendor_patterns = [
                "nvidia/*", "z-ai/*", "minimaxai/*", "google/*", "meta/*",
                "mistralai/*", "qwen/*", "deepseek-ai/*", "microsoft/*",
                "ibm/*", "thudm/*", "writer/*", "bigcode/*", "nv-mistralai/*",
            ]
            for pat in nim_vendor_patterns:
                model_list.append({
                    "model_name": pat,
                    "litellm_params": {
                        "model": f"{prefix}{pat}",
                        "api_base": base_url or "https://integrate.api.nvidia.com/v1",
                        "api_key": api_key,
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

    # ── Smart Routes as litellm model aliases ────────────────────────────────
    # Each enabled SmartRoute with a non-empty default_chain_json is registered
    # as a named model group in the router. The first entry in the chain becomes
    # the primary deployment; subsequent entries act as fallbacks via multiple
    # deployments under the same model_name (litellm.Router round-robins /
    # fails over across them).  This lets external clients pass
    # `model=<route.trigger_model>` (e.g. "essayrubric-eval") without knowing
    # which actual provider/model to use.
    routes_result = await db.execute(
        select(SmartRoute).where(SmartRoute.is_enabled.is_(True))
    )
    smart_routes = routes_result.scalars().all()
    route_alias_count = 0
    providers_by_name = {p.name: p for p in providers}
    for route in smart_routes:
        chain = json.loads(route.default_chain_json or "[]")
        if not chain:
            continue
        trigger = route.trigger_model or route.name
        # Retrieve the API key / base URL for each provider in the chain from
        # already-loaded providers dict (keyed by provider name).
        added = 0
        for entry in chain:
            prov_name = entry.get("provider", "")
            model_id = entry.get("model", "")
            if not prov_name or not model_id:
                continue

            # MLX providers need special treatment: they use openai/ prefix and
            # require a local api_base.  Look up the model_base_url from the
            # mlx/mlx-heavy provider config; if not found, skip to avoid
            # registering an un-routable deployment (litellm rejects unknown
            # providers at startup).
            if prov_name.startswith("mlx"):
                prov = providers_by_name.get(prov_name)
                if not prov:
                    logger.warning(
                        "SmartRoute '%s': provider '%s' not found, skipping model '%s'",
                        trigger, prov_name, model_id,
                    )
                    continue
                config = json.loads(prov.config_json) if prov.config_json else {}
                model_urls = config.get("model_base_urls", {})
                model_base = model_urls.get(model_id, prov.base_url or "").rstrip("/")
                if not model_base:
                    logger.warning(
                        "SmartRoute '%s': no api_base for MLX model '%s', skipping",
                        trigger, model_id,
                    )
                    continue
                if not model_base.endswith("/v1"):
                    model_base = f"{model_base}/v1"
                model_list.append({
                    "model_name": trigger,
                    "litellm_params": {
                        "model": f"openai/{model_id}",
                        "api_base": model_base,
                        "api_key": "not-needed",
                    },
                })
                added += 1
                continue

            prov = providers_by_name.get(prov_name)
            api_key = _get_key(prov) if prov else ""
            prefix = _PROVIDER_PREFIXES.get(prov_name, f"{prov_name}/")
            litellm_model = f"{prefix}{model_id}"
            deployment: dict = {
                "model_name": trigger,
                "litellm_params": {
                    "model": litellm_model,
                },
            }
            if api_key:
                deployment["litellm_params"]["api_key"] = api_key
            model_list.append(deployment)
            added += 1
            route_alias_count += 1
        logger.info(
            "Registered SmartRoute alias: %s -> %d deployment(s)", trigger, added
        )
    logger.info("Total SmartRoute alias deployments added: %d", route_alias_count)

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
