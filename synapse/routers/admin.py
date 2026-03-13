"""Admin API endpoints for managing providers, routes, and API keys."""

import asyncio
import datetime
import json
import logging
import os
from typing import Optional

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import Provider, ApiKey, UsageLog, Route, SmartRoute
from synapse.services.auth import hash_key
from synapse.services.model_types import classify_model_type, filter_language_models
from synapse.routers.audio import get_audio_models

logger = logging.getLogger("synapse.admin")
templates = Jinja2Templates(directory="synapse/templates")


# --- Basic Auth ---

def _check_basic_auth(request: Request) -> bool:
    """Validate Basic Auth credentials from the request."""
    settings = get_settings()
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    import base64
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        user, password = decoded.split(":", 1)
        return secrets.compare_digest(user, settings.admin_user) and \
               secrets.compare_digest(password, settings.admin_password)
    except Exception:
        return False


async def require_admin(request: Request):
    """Dependency that enforces Basic Auth on admin endpoints."""
    if not _check_basic_auth(request):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": 'Basic realm="Synapse Admin"'},
        )


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


# --- Admin UI ---

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    providers = (await db.execute(select(Provider).order_by(Provider.priority))).scalars().all()
    keys = (await db.execute(select(ApiKey))).scalars().all()
    routes = (await db.execute(select(Route).order_by(Route.priority))).scalars().all()
    smart_routes = (await db.execute(select(SmartRoute))).scalars().all()

    # Parse intents for display
    smart_routes_data = []
    for sr in smart_routes:
        intents = json.loads(sr.intents_json) if sr.intents_json else []
        smart_routes_data.append({
            "id": sr.id,
            "name": sr.name,
            "description": sr.description,
            "trigger_model": sr.trigger_model,
            "classifier_model": sr.classifier_model,
            "intents": intents,
            "default_chain": json.loads(sr.default_chain_json) if sr.default_chain_json else [],
            "is_enabled": sr.is_enabled,
        })

    # Usage stats
    total_requests = (await db.execute(select(func.count(UsageLog.id)))).scalar() or 0
    total_cost = (await db.execute(select(func.sum(UsageLog.cost_usd)))).scalar() or 0.0
    avg_latency = (await db.execute(select(func.avg(UsageLog.latency_ms)))).scalar() or 0

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "providers": providers,
        "api_keys": keys,
        "routes": routes,
        "smart_routes": smart_routes_data,
        "stats": {
            "total_requests": total_requests,
            "total_cost": round(total_cost, 4),
            "avg_latency": round(avg_latency),
        },
    })


# --- Provider CRUD ---

class ProviderCreate(BaseModel):
    name: str
    display_name: str
    base_url: str = ""
    is_local: bool = False
    priority: int = 10


class ProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None
    max_concurrent: Optional[int] = None


@router.post("/api/providers")
async def create_provider(data: ProviderCreate, db: AsyncSession = Depends(get_db)):
    # Check uniqueness
    existing = await db.execute(select(Provider).where(Provider.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Provider '{data.name}' already exists")

    provider = Provider(
        name=data.name,
        display_name=data.display_name,
        base_url=data.base_url,
        is_local=data.is_local,
        priority=data.priority,
        is_enabled=True,
    )
    db.add(provider)
    await db.commit()
    return {"status": "ok", "id": provider.id, "name": provider.name}


@router.delete("/api/providers/{provider_id}")
async def delete_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")
    await db.delete(provider)
    await db.commit()
    return {"status": "deleted"}


@router.get("/api/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Provider).order_by(Provider.priority))
    providers = result.scalars().all()
    out = []
    for p in providers:
        config = json.loads(p.config_json) if p.config_json else {}
        out.append({
            "id": p.id, "name": p.name, "display_name": p.display_name,
            "base_url": p.base_url, "is_enabled": p.is_enabled,
            "is_local": p.is_local, "priority": p.priority,
            "avg_latency_ms": p.avg_latency_ms,
            "has_key": bool(p.api_key_value or (
                p.api_key_env and os.environ.get(p.api_key_env)
            )),
            "key_source": "db" if p.api_key_value else (
                "env" if p.api_key_env and os.environ.get(p.api_key_env) else ""
            ),
            "key_preview": (
                p.api_key_value[:8] + "..." if p.api_key_value
                else (os.environ.get(p.api_key_env, "")[:8] + "..."
                      if p.api_key_env and os.environ.get(p.api_key_env)
                      else "")
            ),
            "enabled_models": config.get("enabled_models", []),
            "api_key_expires_at": p.api_key_expires_at.isoformat() if p.api_key_expires_at else None,
            "key_expires_soon": (
                p.api_key_expires_at is not None
                and (p.api_key_expires_at - datetime.datetime.utcnow()).days <= 14
            ) if p.api_key_expires_at else False,
            "key_expired": (
                p.api_key_expires_at is not None
                and p.api_key_expires_at < datetime.datetime.utcnow()
            ) if p.api_key_expires_at else False,
            "key_days_left": (
                (p.api_key_expires_at - datetime.datetime.utcnow()).days
            ) if p.api_key_expires_at else None,
        })
    return out


@router.put("/api/providers/{provider_id}")
async def update_provider(
    provider_id: int, data: ProviderUpdate, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(provider, field, value)
    await db.commit()
    return {"status": "ok"}


class ProviderKeyUpdate(BaseModel):
    api_key: str  # empty string to clear
    expires_at: Optional[str] = None  # ISO date string, e.g. "2026-06-15"


@router.put("/api/providers/{provider_id}/key")
async def set_provider_key(
    provider_id: int, data: ProviderKeyUpdate, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    provider.api_key_value = data.api_key if data.api_key else None

    if data.expires_at:
        provider.api_key_expires_at = datetime.datetime.fromisoformat(data.expires_at)
    elif not data.api_key:
        provider.api_key_expires_at = None  # clear expiry when clearing key

    await db.commit()

    status = "configured" if data.api_key else "cleared"
    return {"status": status, "provider": provider.display_name}


class ProviderExpiryUpdate(BaseModel):
    expires_at: Optional[str] = None  # ISO date or null to clear


@router.put("/api/providers/{provider_id}/expiry")
async def set_provider_expiry(
    provider_id: int, data: ProviderExpiryUpdate, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    if data.expires_at:
        provider.api_key_expires_at = datetime.datetime.fromisoformat(data.expires_at)
    else:
        provider.api_key_expires_at = None
    await db.commit()
    return {"status": "ok", "expires_at": data.expires_at}


class ProviderModelsUpdate(BaseModel):
    enabled_models: list[str]  # empty list = all available


@router.put("/api/providers/{provider_id}/models")
async def set_provider_models(
    provider_id: int, data: ProviderModelsUpdate, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    config = json.loads(provider.config_json) if provider.config_json else {}
    config["enabled_models"] = data.enabled_models
    provider.config_json = json.dumps(config)
    await db.commit()
    return {"status": "ok", "enabled_models": data.enabled_models}


@router.get("/api/providers/{provider_id}/discover")
async def discover_provider_models(
    provider_id: int, db: AsyncSession = Depends(get_db)
):
    """Fetch all available models from a provider using its configured key."""
    settings = get_settings()
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    key = _get_provider_key(provider, settings)
    models = await _fetch_models_for_provider(provider, key, settings)
    models_typed = [
        {"name": m, "type": classify_model_type(m)} for m in sorted(models)
    ]
    return {"provider": provider.name, "models": sorted(models), "models_typed": models_typed}


class ProviderCustomModels(BaseModel):
    custom_models: list[str]


@router.put("/api/providers/{provider_id}/custom-models")
async def set_custom_models(
    provider_id: int, data: ProviderCustomModels, db: AsyncSession = Depends(get_db)
):
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    config = json.loads(provider.config_json) if provider.config_json else {}
    config["custom_models"] = data.custom_models
    provider.config_json = json.dumps(config)
    await db.commit()
    return {"status": "ok", "custom_models": data.custom_models}


class ProviderTestRequest(BaseModel):
    model: str
    message: str = "Responde solo con 'OK' si puedes leer esto."


@router.post("/api/providers/{provider_id}/test")
async def test_provider(
    provider_id: int, data: ProviderTestRequest, db: AsyncSession = Depends(get_db)
):
    """Send a quick test request to a provider to verify connectivity."""
    import time
    import litellm

    settings = get_settings()
    provider = await db.get(Provider, provider_id)
    if not provider:
        raise HTTPException(404, "Provider not found")

    key = _get_provider_key(provider, settings)
    if not key and not provider.is_local:
        return {"success": False, "error": "No API key configured"}

    # Build litellm model string
    from synapse.services.router import router_engine
    target = {
        "provider": provider.name,
        "model": data.model,
        "base_url": provider.base_url or "",
        "api_key": key,
    }
    litellm_model = router_engine._to_litellm_model(target)

    try:
        start = time.monotonic()
        call_kwargs = {
            "model": litellm_model,
            "messages": [{"role": "user", "content": data.message}],
            "max_tokens": 50,
            "stream": False,
        }
        if target.get("base_url"):
            call_kwargs["api_base"] = target["base_url"]
        if key:
            call_kwargs["api_key"] = key

        response = await litellm.acompletion(**call_kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        content = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0

        return {
            "success": True,
            "response": content[:200],
            "latency_ms": elapsed_ms,
            "tokens": tokens,
            "model": data.model,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)[:300],
            "model": data.model,
        }


# --- API Key Management ---

class CreateKeyRequest(BaseModel):
    name: str
    service: str
    allowed_models: str = "*"
    rate_limit_rpm: int = 60
    smart_route_id: Optional[int] = None


@router.post("/api/keys")
async def create_api_key(data: CreateKeyRequest, db: AsyncSession = Depends(get_db)):
    raw_key = ApiKey.generate_key()
    key = ApiKey(
        name=data.name,
        key_hash=hash_key(raw_key),
        key_prefix=raw_key[:10],
        service=data.service,
        allowed_models=data.allowed_models,
        rate_limit_rpm=data.rate_limit_rpm,
        smart_route_id=data.smart_route_id,
    )
    db.add(key)
    await db.commit()
    # Return raw key only once — it cannot be retrieved after this
    return {"key": raw_key, "id": key.id, "name": key.name}


@router.get("/api/keys")
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey))
    keys = result.scalars().all()

    # Fetch smart route names for display
    sr_names = {}
    sr_ids = {k.smart_route_id for k in keys if k.smart_route_id}
    if sr_ids:
        sr_result = await db.execute(
            select(SmartRoute.id, SmartRoute.name).where(SmartRoute.id.in_(sr_ids))
        )
        sr_names = {row[0]: row[1] for row in sr_result.all()}

    return [
        {
            "id": k.id, "name": k.name, "key_prefix": k.key_prefix,
            "service": k.service, "is_active": k.is_active,
            "allowed_models": k.allowed_models, "rate_limit_rpm": k.rate_limit_rpm,
            "smart_route_id": k.smart_route_id,
            "smart_route_name": sr_names.get(k.smart_route_id, ""),
        }
        for k in keys
    ]


@router.delete("/api/keys/{key_id}")
async def revoke_api_key(key_id: int, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "Key not found")
    key.is_active = False
    await db.commit()
    return {"status": "revoked"}


# --- Route Management ---

class RouteCreate(BaseModel):
    name: str
    description: str = ""
    model_pattern: str
    provider_chain: list[dict]  # [{"provider": "ollama", "model": "llama3"}, ...]
    priority: int = 10
    max_context_tokens: int = 0


@router.post("/api/routes")
async def create_route(data: RouteCreate, db: AsyncSession = Depends(get_db)):
    route = Route(
        name=data.name,
        description=data.description,
        model_pattern=data.model_pattern,
        provider_chain=json.dumps(data.provider_chain),
        priority=data.priority,
        max_context_tokens=data.max_context_tokens,
    )
    db.add(route)
    await db.commit()
    return {"status": "ok", "id": route.id}


@router.get("/api/routes")
async def list_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Route).order_by(Route.priority))
    routes = result.scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "description": r.description,
            "model_pattern": r.model_pattern,
            "provider_chain": json.loads(r.provider_chain),
            "is_enabled": r.is_enabled, "priority": r.priority,
        }
        for r in routes
    ]


@router.put("/api/routes/{route_id}")
async def update_route(
    route_id: int, data: RouteCreate, db: AsyncSession = Depends(get_db)
):
    route = await db.get(Route, route_id)
    if not route:
        raise HTTPException(404, "Route not found")
    route.name = data.name
    route.description = data.description
    route.model_pattern = data.model_pattern
    route.provider_chain = json.dumps(data.provider_chain)
    route.priority = data.priority
    route.max_context_tokens = data.max_context_tokens
    await db.commit()
    return {"status": "ok"}


@router.delete("/api/routes/{route_id}")
async def delete_route(route_id: int, db: AsyncSession = Depends(get_db)):
    route = await db.get(Route, route_id)
    if not route:
        raise HTTPException(404, "Route not found")
    await db.delete(route)
    await db.commit()
    return {"status": "deleted"}


# --- Smart Routes (Intent-Based Routing) ---

class IntentConfig(BaseModel):
    name: str              # e.g. "coding"
    description: str       # e.g. "Programación, debugging, revisión de código"
    provider_chain: list[dict]  # [{provider, model}, ...]


class SmartRouteCreate(BaseModel):
    name: str
    description: str = ""
    trigger_model: str             # e.g. "auto"
    classifier_model: str          # e.g. "llama3.1:8b"
    classifier_prompt: str = ""    # auto-generated if empty
    intents: list[IntentConfig]
    default_chain: list[dict]      # fallback chain


@router.post("/api/smart-routes")
async def create_smart_route(data: SmartRouteCreate, db: AsyncSession = Depends(get_db)):
    sr = SmartRoute(
        name=data.name,
        description=data.description,
        trigger_model=data.trigger_model,
        classifier_model=data.classifier_model,
        classifier_prompt=data.classifier_prompt,
        intents_json=json.dumps([i.model_dump() for i in data.intents]),
        default_chain_json=json.dumps(data.default_chain),
    )
    db.add(sr)
    await db.commit()
    return {"status": "ok", "id": sr.id, "trigger_model": sr.trigger_model}


@router.get("/api/smart-routes")
async def list_smart_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SmartRoute))
    routes = result.scalars().all()
    return [
        {
            "id": sr.id, "name": sr.name, "description": sr.description,
            "trigger_model": sr.trigger_model, "classifier_model": sr.classifier_model,
            "intents": json.loads(sr.intents_json),
            "default_chain": json.loads(sr.default_chain_json),
            "is_enabled": sr.is_enabled,
        }
        for sr in routes
    ]


@router.put("/api/smart-routes/{route_id}")
async def update_smart_route(
    route_id: int, data: SmartRouteCreate, db: AsyncSession = Depends(get_db)
):
    sr = await db.get(SmartRoute, route_id)
    if not sr:
        raise HTTPException(404, "Smart route not found")
    sr.name = data.name
    sr.description = data.description
    sr.trigger_model = data.trigger_model
    sr.classifier_model = data.classifier_model
    sr.classifier_prompt = data.classifier_prompt
    sr.intents_json = json.dumps([i.model_dump() for i in data.intents])
    sr.default_chain_json = json.dumps(data.default_chain)
    await db.commit()
    return {"status": "ok"}


@router.delete("/api/smart-routes/{route_id}")
async def delete_smart_route(route_id: int, db: AsyncSession = Depends(get_db)):
    sr = await db.get(SmartRoute, route_id)
    if not sr:
        raise HTTPException(404, "Smart route not found")
    await db.delete(sr)
    await db.commit()
    return {"status": "deleted"}


@router.put("/api/smart-routes/{route_id}/toggle")
async def toggle_smart_route(route_id: int, db: AsyncSession = Depends(get_db)):
    sr = await db.get(SmartRoute, route_id)
    if not sr:
        raise HTTPException(404, "Smart route not found")
    sr.is_enabled = not sr.is_enabled
    await db.commit()
    return {"status": "ok", "is_enabled": sr.is_enabled}


# --- Helpers for provider key/model resolution ---

KNOWN_MODELS = {
    "anthropic": [
        "claude-opus-4-20250514", "claude-sonnet-4-20250514",
        "claude-sonnet-4-5-20250514",
        "claude-haiku-4-5-20251001",
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "perplexity": [
        "sonar-pro", "sonar", "sonar-reasoning-pro", "sonar-reasoning",
        "sonar-deep-research",
    ],
}


def _get_provider_key(provider: Provider, settings) -> str:
    """Get API key: DB value > env var > settings map."""
    if provider.api_key_value:
        return provider.api_key_value
    if provider.api_key_env:
        val = os.environ.get(provider.api_key_env, "")
        if val:
            return val
    # Fallback to settings
    settings_map = {
        "groq": settings.groq_api_key,
        "nvidia": settings.nvidia_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "perplexity": settings.perplexity_api_key,
    }
    return settings_map.get(provider.name, "")


OPENAI_COMPAT_BASES = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "perplexity": "https://api.perplexity.ai",
}


async def _fetch_models_for_provider(provider: Provider, key: str, settings) -> list[str]:
    """Fetch all available models from a provider via its API."""
    name = provider.name
    models = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            if name == "ollama":
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]

            elif key and name == "anthropic":
                # Anthropic has /v1/models with x-api-key header
                resp = await client.get(
                    "https://api.anthropic.com/v1/models?limit=100",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    for m in resp.json().get("data", []):
                        models.append(m["id"])
                else:
                    # Fallback to known models if API fails
                    models = KNOWN_MODELS.get(name, [])

            elif key and name == "gemini":
                resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=100"
                )
                if resp.status_code == 200:
                    for m in resp.json().get("models", []):
                        model_id = m.get("name", "").replace("models/", "")
                        if model_id:
                            models.append(model_id)

            elif key and name in OPENAI_COMPAT_BASES:
                # OpenAI-compatible /v1/models endpoint
                base = provider.base_url or OPENAI_COMPAT_BASES.get(name, "")
                if base:
                    url = f"{base.rstrip('/')}/models"
                    resp = await client.get(
                        url, headers={"Authorization": f"Bearer {key}"}
                    )
                    if resp.status_code == 200:
                        for m in resp.json().get("data", []):
                            models.append(m["id"])
                    elif name in KNOWN_MODELS:
                        models = KNOWN_MODELS[name]

            elif key and name in KNOWN_MODELS:
                # Fallback for providers without model listing API
                models = KNOWN_MODELS[name]

    except Exception as e:
        logger.debug(f"Could not fetch models for {name}: {e}")
        # Fallback to known models on error
        if name in KNOWN_MODELS:
            models = KNOWN_MODELS[name]

    return models


# --- Metrics ---

@router.get("/api/models")
async def list_available_models(
    model_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Query all enabled providers for their available models.

    Optional filter: ?model_type=language (language, image, tts, audio, embedding, moderation, rerank)
    """
    settings = get_settings()
    result = await db.execute(
        select(Provider).where(Provider.is_enabled.is_(True)).order_by(Provider.priority)
    )
    providers = result.scalars().all()

    async def fetch_provider_models(provider: Provider) -> dict:
        name = provider.name
        key = _get_provider_key(provider, settings)
        configured = bool(key) or provider.is_local
        discovered = await _fetch_models_for_provider(provider, key, settings)

        # Merge custom (manually added) models
        config = json.loads(provider.config_json) if provider.config_json else {}
        custom = config.get("custom_models", [])
        all_models = sorted(set(discovered + custom))

        # Apply enabled_models filter
        enabled = config.get("enabled_models", [])
        if enabled:
            enabled_set = set(enabled)
            models = [m for m in all_models if m in enabled_set]
        else:
            models = all_models

        # Classify each model
        models_with_types = [
            {"name": m, "type": classify_model_type(m)} for m in sorted(models)
        ]
        all_models_with_types = [
            {"name": m, "type": classify_model_type(m)} for m in all_models
        ]

        # Apply type filter if requested
        if model_type:
            models_with_types = [m for m in models_with_types if m["type"] == model_type]

        return {
            "provider": name,
            "display_name": provider.display_name,
            "configured": configured,
            "models": [m["name"] for m in models_with_types],
            "models_typed": models_with_types,
            "all_models": all_models,
            "all_models_typed": all_models_with_types,
            "custom_models": custom,
        }

    tasks = [fetch_provider_models(p) for p in providers]
    provider_results = await asyncio.gather(*tasks)

    all_models = []
    all_models_typed = []
    for pr in provider_results:
        all_models.extend(pr["models"])
        all_models_typed.extend(pr["models_typed"])

    # Deduplicate
    seen = set()
    unique_typed = []
    for m in all_models_typed:
        if m["name"] not in seen:
            seen.add(m["name"])
            unique_typed.append(m)

    return {
        "models": sorted(set(all_models)),
        "models_typed": sorted(unique_typed, key=lambda x: x["name"]),
        "by_provider": provider_results,
    }


@router.get("/api/audio-models")
async def list_audio_models():
    """List available local audio models (STT + TTS)."""
    return get_audio_models()


@router.get("/api/services")
async def list_services(db: AsyncSession = Depends(get_db)):
    """Return distinct service names from existing API keys."""
    result = await db.execute(
        select(ApiKey.service).where(ApiKey.is_active.is_(True)).distinct()
    )
    services = [row[0] for row in result.all()]
    return {"services": sorted(services)}


@router.get("/api/metrics")
async def get_metrics(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    # Recent logs
    result = await db.execute(
        select(UsageLog).order_by(desc(UsageLog.created_at)).limit(limit)
    )
    logs = result.scalars().all()

    # Per-provider stats
    provider_stats = await db.execute(
        select(
            UsageLog.provider,
            func.count(UsageLog.id).label("requests"),
            func.sum(UsageLog.total_tokens).label("tokens"),
            func.sum(UsageLog.cost_usd).label("cost"),
            func.avg(UsageLog.latency_ms).label("avg_latency"),
        ).group_by(UsageLog.provider)
    )

    return {
        "recent": [
            {
                "id": l.id, "provider": l.provider, "model": l.model,
                "tokens": l.total_tokens, "latency_ms": l.latency_ms,
                "cost_usd": l.cost_usd, "status": l.status,
                "created_at": l.created_at.isoformat(),
            }
            for l in logs
        ],
        "by_provider": [
            {
                "provider": row.provider, "requests": row.requests,
                "tokens": row.tokens or 0, "cost": round(row.cost or 0, 4),
                "avg_latency": round(row.avg_latency or 0),
            }
            for row in provider_stats
        ],
    }
