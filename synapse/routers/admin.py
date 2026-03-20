"""Admin API endpoints for managing providers, routes, and API keys."""

import asyncio
import calendar
import datetime
import io
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
from sqlalchemy import select, func, desc, case
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import Provider, ApiKey, ApiKeySmartRoute, UsageLog, Route, SmartRoute, ArenaBattle, ArenaCategory, ArenaResult
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
            "classifier_chain": json.loads(sr.classifier_chain_json) if sr.classifier_chain_json else [],
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
    smart_route_ids: list[int] = []


class UpdateKeyRequest(BaseModel):
    name: Optional[str] = None
    service: Optional[str] = None
    allowed_models: Optional[str] = None
    rate_limit_rpm: Optional[int] = None
    smart_route_ids: Optional[list[int]] = None


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
    )
    db.add(key)
    await db.flush()  # get key.id

    # Insert smart route associations
    for sr_id in data.smart_route_ids:
        db.add(ApiKeySmartRoute(api_key_id=key.id, smart_route_id=sr_id))

    await db.commit()
    return {"key": raw_key, "id": key.id, "name": key.name}


@router.get("/api/keys")
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey))
    keys = result.scalars().all()

    # Fetch smart route assignments from junction table
    key_routes: dict[int, list[dict]] = {}
    if keys:
        sr_result = await db.execute(
            select(
                ApiKeySmartRoute.api_key_id,
                SmartRoute.id,
                SmartRoute.name,
            )
            .join(SmartRoute, SmartRoute.id == ApiKeySmartRoute.smart_route_id)
        )
        for row in sr_result.all():
            key_routes.setdefault(row[0], []).append({"id": row[1], "name": row[2]})

    return [
        {
            "id": k.id, "name": k.name, "key_prefix": k.key_prefix,
            "service": k.service, "is_active": k.is_active,
            "allowed_models": k.allowed_models, "rate_limit_rpm": k.rate_limit_rpm,
            "smart_routes": key_routes.get(k.id, []),
        }
        for k in keys
    ]


@router.put("/api/keys/{key_id}")
async def update_api_key(key_id: int, data: UpdateKeyRequest, db: AsyncSession = Depends(get_db)):
    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(404, "Key not found")
    if not key.is_active:
        raise HTTPException(400, "Cannot edit a revoked key")

    if data.name is not None:
        key.name = data.name
    if data.service is not None:
        key.service = data.service
    if data.allowed_models is not None:
        key.allowed_models = data.allowed_models
    if data.rate_limit_rpm is not None:
        key.rate_limit_rpm = data.rate_limit_rpm

    # Update smart route associations
    if data.smart_route_ids is not None:
        # Remove existing
        existing = await db.execute(
            select(ApiKeySmartRoute).where(ApiKeySmartRoute.api_key_id == key_id)
        )
        for assoc in existing.scalars().all():
            await db.delete(assoc)
        # Add new
        for sr_id in data.smart_route_ids:
            db.add(ApiKeySmartRoute(api_key_id=key_id, smart_route_id=sr_id))

    await db.commit()
    return {"status": "updated", "id": key_id}


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
    classifier_model: str          # e.g. "llama3.1:8b" (backward compat)
    classifier_chain: list[dict] = []  # [{provider, model}, ...] with fallback
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
        classifier_chain_json=json.dumps(data.classifier_chain),
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
            "classifier_chain": json.loads(sr.classifier_chain_json or "[]"),
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
    sr.classifier_chain_json = json.dumps(data.classifier_chain)
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


# --- Arena ---

@router.get("/api/arena/presets")
async def list_arena_presets(db: AsyncSession = Depends(get_db)):
    """Return arena presets grouped by category, including custom categories."""
    from synapse.services.arena_presets import ARENA_PRESETS, ARENA_CATEGORIES
    # Merge built-in + custom categories from DB
    rows = (await db.execute(
        select(ArenaCategory).order_by(ArenaCategory.name)
    )).scalars().all()
    custom_map = {r.name: r.id for r in rows if r.name not in ARENA_CATEGORIES}
    all_categories = list(ARENA_CATEGORIES) + sorted(custom_map.keys())
    by_cat = {c: [] for c in all_categories}
    for p in ARENA_PRESETS:
        by_cat.setdefault(p["category"], []).append(p)
    return {
        "categories": all_categories,
        "presets": by_cat,
        "custom_categories": custom_map,  # {name: id} for deletable categories
    }


# --- Arena categories CRUD ---

class ArenaCategoryCreate(BaseModel):
    name: str


@router.get("/api/arena/categories")
async def list_arena_categories(db: AsyncSession = Depends(get_db)):
    from synapse.services.arena_presets import ARENA_CATEGORIES
    rows = (await db.execute(
        select(ArenaCategory).order_by(ArenaCategory.name)
    )).scalars().all()
    custom = [{"id": r.id, "name": r.name} for r in rows]
    return {"builtin": list(ARENA_CATEGORIES), "custom": custom}


@router.post("/api/arena/categories")
async def create_arena_category(data: ArenaCategoryCreate, db: AsyncSession = Depends(get_db)):
    name = data.name.strip().lower().replace(" ", "_")
    if not name:
        raise HTTPException(400, "Nombre vacío")
    existing = (await db.execute(
        select(ArenaCategory).where(ArenaCategory.name == name)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"La categoría '{name}' ya existe")
    cat = ArenaCategory(name=name)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return {"status": "ok", "id": cat.id, "name": cat.name}


@router.delete("/api/arena/categories/{cat_id}")
async def delete_arena_category(cat_id: int, db: AsyncSession = Depends(get_db)):
    cat = await db.get(ArenaCategory, cat_id)
    if not cat:
        raise HTTPException(404, "Categoría no encontrada")
    await db.delete(cat)
    await db.commit()
    return {"status": "ok"}


class ArenaBattleCreate(BaseModel):
    prompt: str
    category: str = "custom"
    temperature: float = 0.7
    max_tokens: int = 2048


@router.post("/api/arena/battles")
async def create_arena_battle(data: ArenaBattleCreate, db: AsyncSession = Depends(get_db)):
    battle = ArenaBattle(
        prompt=data.prompt,
        category=data.category,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
    )
    db.add(battle)
    await db.commit()
    return {"status": "ok", "id": battle.id}


@router.get("/api/arena/battles")
async def list_arena_battles(
    limit: int = 50,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(ArenaBattle).order_by(desc(ArenaBattle.created_at)).limit(limit)
    if category:
        q = q.where(ArenaBattle.category == category)
    result = await db.execute(q)
    battles = result.scalars().all()

    out = []
    for b in battles:
        # Fetch results for each battle
        res = await db.execute(
            select(ArenaResult).where(ArenaResult.battle_id == b.id)
        )
        results = res.scalars().all()
        out.append({
            "id": b.id,
            "prompt": b.prompt,
            "category": b.category,
            "temperature": b.temperature,
            "max_tokens": b.max_tokens,
            "created_at": b.created_at.isoformat(),
            "results": [
                {
                    "id": r.id,
                    "provider": r.provider,
                    "model": r.model,
                    "ttft_ms": r.ttft_ms,
                    "tokens_per_sec": r.tokens_per_sec,
                    "completion_tokens": r.completion_tokens,
                    "total_time_ms": r.total_time_ms,
                    "cost_usd": r.cost_usd,
                    "rating": r.rating,
                    "status": r.status,
                }
                for r in results
            ],
        })
    return out


class ArenaResultCreate(BaseModel):
    provider: str
    model: str
    ttft_ms: int = 0
    tokens_per_sec: float = 0.0
    completion_tokens: int = 0
    total_time_ms: int = 0
    cost_usd: float = 0.0
    response_text: str = ""
    status: str = "success"


@router.post("/api/arena/battles/{battle_id}/results")
async def create_arena_result(
    battle_id: int, data: ArenaResultCreate, db: AsyncSession = Depends(get_db)
):
    battle = await db.get(ArenaBattle, battle_id)
    if not battle:
        raise HTTPException(404, "Battle not found")

    result = ArenaResult(
        battle_id=battle_id,
        provider=data.provider,
        model=data.model,
        ttft_ms=data.ttft_ms,
        tokens_per_sec=data.tokens_per_sec,
        completion_tokens=data.completion_tokens,
        total_time_ms=data.total_time_ms,
        cost_usd=data.cost_usd,
        response_text=data.response_text,
        status=data.status,
    )
    db.add(result)
    await db.commit()
    return {"status": "ok", "id": result.id}


class ArenaRating(BaseModel):
    rating: int  # 1-5


@router.put("/api/arena/results/{result_id}/rate")
async def rate_arena_result(
    result_id: int, data: ArenaRating, db: AsyncSession = Depends(get_db)
):
    result = await db.get(ArenaResult, result_id)
    if not result:
        raise HTTPException(404, "Result not found")
    if data.rating < 1 or data.rating > 5:
        raise HTTPException(400, "Rating must be 1-5")
    result.rating = data.rating
    await db.commit()
    return {"status": "ok", "rating": result.rating}


@router.get("/api/arena/scorecard")
async def arena_scorecard(
    min_battles: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """Rankings: avg rating per model and category."""
    q = await db.execute(
        select(
            ArenaResult.provider,
            ArenaResult.model,
            ArenaBattle.category,
            func.avg(ArenaResult.rating).label("avg_rating"),
            func.count(ArenaResult.id).label("count"),
            func.avg(ArenaResult.tokens_per_sec).label("avg_tps"),
            func.avg(ArenaResult.ttft_ms).label("avg_ttft"),
        )
        .join(ArenaBattle, ArenaResult.battle_id == ArenaBattle.id)
        .where(ArenaResult.rating.isnot(None))
        .group_by(ArenaResult.provider, ArenaResult.model, ArenaBattle.category)
        .having(func.count(ArenaResult.id) >= min_battles)
        .order_by(desc("avg_rating"))
    )
    rows = q.all()
    return [
        {
            "provider": r.provider,
            "model": r.model,
            "category": r.category,
            "avg_rating": round(float(r.avg_rating), 2),
            "count": r.count,
            "avg_tps": round(float(r.avg_tps), 1) if r.avg_tps else 0,
            "avg_ttft": round(float(r.avg_ttft)) if r.avg_ttft else 0,
        }
        for r in rows
    ]


# Mapping from smart route intent names to arena categories
INTENT_CATEGORY_MAP = {
    "medicina": "medicine",
    "medical": "medicine",
    "medicine": "medicine",
    "coding": "coding",
    "programación": "coding",
    "code": "coding",
    "tool_use": "tool_use",
    "herramientas": "tool_use",
    "tools": "tool_use",
    "reasoning": "reasoning",
    "razonamiento": "reasoning",
    "simple": "simple",
    "general": "simple",
    "conversación": "simple",
    "spanish": "spanish",
    "español": "spanish",
}


@router.get("/api/arena/recommendations/{smart_route_id}")
async def arena_recommendations(
    smart_route_id: int, db: AsyncSession = Depends(get_db)
):
    """Compare scorecard vs current Smart Route assignment."""
    sr = await db.get(SmartRoute, smart_route_id)
    if not sr:
        raise HTTPException(404, "Smart route not found")

    intents = json.loads(sr.intents_json) if sr.intents_json else []

    # Get top-rated model per category
    scorecard_q = await db.execute(
        select(
            ArenaResult.provider,
            ArenaResult.model,
            ArenaBattle.category,
            func.avg(ArenaResult.rating).label("avg_rating"),
            func.count(ArenaResult.id).label("count"),
        )
        .join(ArenaBattle, ArenaResult.battle_id == ArenaBattle.id)
        .where(ArenaResult.rating.isnot(None))
        .group_by(ArenaResult.provider, ArenaResult.model, ArenaBattle.category)
        .having(func.count(ArenaResult.id) >= 1)
        .order_by(desc("avg_rating"))
    )
    scorecard = scorecard_q.all()

    # Build best model per category
    best_by_cat = {}
    for row in scorecard:
        if row.category not in best_by_cat:
            best_by_cat[row.category] = {
                "provider": row.provider,
                "model": row.model,
                "avg_rating": round(float(row.avg_rating), 2),
                "count": row.count,
            }

    # Enrich mapping with custom categories (auto-map: name → name)
    custom_cats = (await db.execute(select(ArenaCategory))).scalars().all()
    intent_map = dict(INTENT_CATEGORY_MAP)
    for c in custom_cats:
        intent_map.setdefault(c.name, c.name)

    recommendations = []
    for intent in intents:
        intent_name = intent.get("name", "").lower()
        category = intent_map.get(intent_name)
        current_chain = intent.get("provider_chain", [])
        current = current_chain[0] if current_chain else {}

        rec = {
            "intent_name": intent.get("name", ""),
            "intent_description": intent.get("description", ""),
            "category": category,
            "current_provider": current.get("provider", ""),
            "current_model": current.get("model", ""),
            "current_rating": None,
            "recommended_provider": None,
            "recommended_model": None,
            "recommended_rating": None,
            "improvement": None,
        }

        if category and category in best_by_cat:
            best = best_by_cat[category]
            rec["recommended_provider"] = best["provider"]
            rec["recommended_model"] = best["model"]
            rec["recommended_rating"] = best["avg_rating"]

            # Find current model's rating in this category
            for row in scorecard:
                if (row.category == category
                        and row.provider == current.get("provider")
                        and row.model == current.get("model")):
                    rec["current_rating"] = round(float(row.avg_rating), 2)
                    break

            if rec["current_rating"] and rec["recommended_rating"]:
                rec["improvement"] = round(rec["recommended_rating"] - rec["current_rating"], 2)

        recommendations.append(rec)

    return {
        "smart_route_id": sr.id,
        "smart_route_name": sr.name,
        "recommendations": recommendations,
    }


class ApplyRecommendation(BaseModel):
    smart_route_id: int
    intent_name: str
    provider: str
    model: str


@router.post("/api/arena/apply-recommendation")
async def apply_arena_recommendation(
    data: ApplyRecommendation, db: AsyncSession = Depends(get_db)
):
    """Update a Smart Route intent with the recommended model."""
    sr = await db.get(SmartRoute, data.smart_route_id)
    if not sr:
        raise HTTPException(404, "Smart route not found")

    intents = json.loads(sr.intents_json) if sr.intents_json else []
    updated = False

    for intent in intents:
        if intent.get("name") == data.intent_name:
            chain = intent.get("provider_chain", [])
            if chain:
                chain[0] = {"provider": data.provider, "model": data.model}
            else:
                intent["provider_chain"] = [{"provider": data.provider, "model": data.model}]
            updated = True
            break

    if not updated:
        raise HTTPException(404, f"Intent '{data.intent_name}' not found in smart route")

    sr.intents_json = json.dumps(intents)
    await db.commit()
    return {"status": "ok", "intent": data.intent_name, "model": f"{data.provider}/{data.model}"}


# --- Helpers for provider key/model resolution ---

KNOWN_MODELS = {
    "anthropic": [
        "claude-opus-4-20250514", "claude-sonnet-4-20250514",
        "claude-sonnet-4-5-20250514",
        "claude-haiku-4-5-20251001",
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "minimax": [
        "MiniMax-M2.7", "MiniMax-M2.7-highspeed",
        "MiniMax-M2.5", "MiniMax-M2.5-highspeed",
        "MiniMax-M2.1", "MiniMax-M2.1-highspeed",
        "MiniMax-M2",
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
            if name == "ollama" or name.startswith("ollama-"):
                base = provider.base_url or settings.ollama_base_url
                resp = await client.get(f"{base.rstrip('/')}/api/tags")
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


@router.get("/api/analytics")
async def get_analytics(
    days: int = 7,
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Comprehensive analytics endpoint for the dashboard.

    Supports two modes:
    - days=N (legacy): last N days, days=0 for all time
    - start=YYYY-MM-DD&end=YYYY-MM-DD: custom date range
    """
    # Date filter
    if start and end:
        try:
            start_dt = datetime.datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.datetime.strptime(end, "%Y-%m-%d") + datetime.timedelta(days=1)
            date_filter = (UsageLog.created_at >= start_dt) & (UsageLog.created_at < end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")
    elif days > 0:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        date_filter = UsageLog.created_at >= cutoff
    else:
        date_filter = True  # no filter — all time

    base = select(UsageLog).where(date_filter)

    # Summary
    summary_q = await db.execute(
        select(
            func.count(UsageLog.id).label("total_requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("total_cost"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.sum(case((UsageLog.status == "error", 1), else_=0)).label("error_count"),
            func.sum(case((UsageLog.status == "fallback", 1), else_=0)).label("fallback_count"),
        ).where(date_filter)
    )
    s = summary_q.one()
    summary = {
        "total_requests": s.total_requests,
        "total_cost": round(float(s.total_cost), 4),
        "total_tokens": int(s.total_tokens),
        "avg_latency": round(float(s.avg_latency)),
        "error_count": int(s.error_count or 0),
        "fallback_count": int(s.fallback_count or 0),
    }

    # By provider
    prov_q = await db.execute(
        select(
            UsageLog.provider,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.sum(case((UsageLog.status == "error", 1), else_=0)).label("errors"),
            func.sum(case((UsageLog.status == "fallback", 1), else_=0)).label("fallbacks"),
        ).where(date_filter).group_by(UsageLog.provider)
    )
    by_provider = []
    for row in prov_q:
        req = row.requests
        by_provider.append({
            "provider": row.provider,
            "requests": req,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "avg_latency": round(float(row.avg_latency)),
            "error_rate": round((row.errors or 0) / req * 100, 1) if req else 0,
            "fallback_rate": round((row.fallbacks or 0) / req * 100, 1) if req else 0,
        })

    # By model (top 20)
    model_q = await db.execute(
        select(
            UsageLog.model,
            UsageLog.provider,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
        ).where(date_filter)
        .group_by(UsageLog.model, UsageLog.provider)
        .order_by(desc("requests"))
        .limit(20)
    )
    by_model = [
        {
            "model": row.model,
            "provider": row.provider,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "avg_latency": round(float(row.avg_latency)),
        }
        for row in model_q
    ]

    # By service (join with api_keys)
    svc_q = await db.execute(
        select(
            ApiKey.service,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
        ).join(ApiKey, UsageLog.api_key_id == ApiKey.id)
        .where(date_filter)
        .group_by(ApiKey.service)
    )
    by_service = [
        {
            "service": row.service,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
        }
        for row in svc_q
    ]

    # Timeline (by day)
    timeline_q = await db.execute(
        select(
            func.date(UsageLog.created_at).label("date"),
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
        ).where(date_filter)
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at))
    )
    timeline = [
        {
            "date": str(row.date),
            "requests": row.requests,
            "cost": round(float(row.cost), 4),
            "tokens": int(row.tokens),
        }
        for row in timeline_q
    ]

    # By status
    status_q = await db.execute(
        select(
            UsageLog.status,
            func.count(UsageLog.id).label("count"),
        ).where(date_filter).group_by(UsageLog.status)
    )
    by_status = [
        {"status": row.status, "count": row.count}
        for row in status_q
    ]

    # By smart route + intent
    intent_q = await db.execute(
        select(
            UsageLog.smart_route_name,
            UsageLog.intent,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.sum(case((UsageLog.status == "error", 1), else_=0)).label("errors"),
            func.sum(case((UsageLog.status == "fallback", 1), else_=0)).label("fallbacks"),
        ).where(date_filter, UsageLog.smart_route_name != "")
        .group_by(UsageLog.smart_route_name, UsageLog.intent)
        .order_by(UsageLog.smart_route_name, desc("requests"))
    )
    by_intent = [
        {
            "smart_route": row.smart_route_name,
            "intent": row.intent,
            "requests": row.requests,
            "cost": round(float(row.cost), 4),
            "avg_latency": round(float(row.avg_latency)),
            "errors": int(row.errors or 0),
            "fallbacks": int(row.fallbacks or 0),
        }
        for row in intent_q
    ]

    # Provider latency timeline (daily avg per provider)
    latency_q = await db.execute(
        select(
            func.date(UsageLog.created_at).label("date"),
            UsageLog.provider,
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.count(UsageLog.id).label("requests"),
        ).where(date_filter, UsageLog.status != "error")
        .group_by(func.date(UsageLog.created_at), UsageLog.provider)
        .order_by(func.date(UsageLog.created_at))
    )
    latency_timeline = [
        {
            "date": str(row.date),
            "provider": row.provider,
            "avg_latency": round(float(row.avg_latency)),
            "requests": row.requests,
        }
        for row in latency_q
    ]

    # Fallback details: which provider failed -> which took over
    fallback_q = await db.execute(
        select(
            UsageLog.route_path,
            func.count(UsageLog.id).label("count"),
        ).where(date_filter, UsageLog.status == "fallback")
        .group_by(UsageLog.route_path)
        .order_by(desc("count"))
        .limit(20)
    )
    fallback_paths = [
        {"route_path": row.route_path, "count": row.count}
        for row in fallback_q
    ]

    # Cost vs Quality: cross Arena ratings with usage_log costs per model
    cvq_q = await db.execute(
        select(
            UsageLog.provider,
            UsageLog.model,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("total_cost"),
            func.coalesce(func.avg(UsageLog.cost_usd), 0).label("avg_cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
        ).where(date_filter, UsageLog.status != "error")
        .group_by(UsageLog.provider, UsageLog.model)
        .having(func.count(UsageLog.id) >= 1)
        .order_by(desc("requests"))
    )
    # Get Arena ratings per model (all-time, independent of date filter)
    arena_q = await db.execute(
        select(
            ArenaResult.provider,
            ArenaResult.model,
            func.avg(ArenaResult.rating).label("avg_rating"),
            func.count(ArenaResult.id).label("arena_battles"),
        )
        .where(ArenaResult.rating.isnot(None))
        .group_by(ArenaResult.provider, ArenaResult.model)
    )
    arena_ratings = {
        (r.provider, r.model): {
            "avg_rating": round(float(r.avg_rating), 2),
            "arena_battles": r.arena_battles,
        }
        for r in arena_q
    }

    cost_vs_quality = []
    for row in cvq_q:
        arena = arena_ratings.get((row.provider, row.model), {})
        avg_rating = arena.get("avg_rating")
        total_cost = float(row.total_cost)
        entry = {
            "provider": row.provider,
            "model": row.model,
            "requests": row.requests,
            "total_cost": round(total_cost, 4),
            "avg_cost_per_req": round(float(row.avg_cost), 6),
            "avg_latency": round(float(row.avg_latency)),
            "total_tokens": int(row.total_tokens),
            "avg_rating": avg_rating,
            "arena_battles": arena.get("arena_battles", 0),
            "score_per_dollar": round(avg_rating / total_cost, 1) if avg_rating and total_cost > 0 else None,
        }
        cost_vs_quality.append(entry)

    return {
        "summary": summary,
        "by_provider": by_provider,
        "by_model": by_model,
        "by_service": by_service,
        "timeline": timeline,
        "by_status": by_status,
        "by_intent": by_intent,
        "latency_timeline": latency_timeline,
        "fallback_paths": fallback_paths,
        "cost_vs_quality": cost_vs_quality,
    }


@router.get("/api/reports/monthly")
async def get_monthly_report(
    year: int,
    month: int,
    format: str = "json",
    db: AsyncSession = Depends(get_db),
):
    """Generate monthly cost report by provider, model, and smart route.

    format=json returns data, format=pdf returns a downloadable PDF.
    """
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="Mes inválido (1-12)")

    _, last_day = calendar.monthrange(year, month)
    start_dt = datetime.datetime(year, month, 1)
    end_dt = datetime.datetime(year, month, last_day, 23, 59, 59)
    date_filter = (UsageLog.created_at >= start_dt) & (UsageLog.created_at <= end_dt)

    # Summary
    summary_q = await db.execute(
        select(
            func.count(UsageLog.id).label("total_requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("total_cost"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.sum(case((UsageLog.status == "error", 1), else_=0)).label("error_count"),
            func.sum(case((UsageLog.status == "fallback", 1), else_=0)).label("fallback_count"),
        ).where(date_filter)
    )
    s = summary_q.one()
    summary = {
        "total_requests": s.total_requests,
        "total_cost": round(float(s.total_cost), 4),
        "total_tokens": int(s.total_tokens),
        "prompt_tokens": int(s.prompt_tokens),
        "completion_tokens": int(s.completion_tokens),
        "avg_latency": round(float(s.avg_latency)),
        "error_count": int(s.error_count or 0),
        "fallback_count": int(s.fallback_count or 0),
    }

    # By provider
    prov_q = await db.execute(
        select(
            UsageLog.provider,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
            func.coalesce(func.avg(UsageLog.cost_usd), 0).label("avg_cost"),
        ).where(date_filter)
        .group_by(UsageLog.provider)
        .order_by(desc("cost"))
    )
    by_provider = [
        {
            "provider": row.provider,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "avg_latency": round(float(row.avg_latency)),
            "avg_cost": round(float(row.avg_cost), 6),
            "pct": 0.0,  # filled below
        }
        for row in prov_q
    ]
    total_cost = summary["total_cost"]
    for p in by_provider:
        p["pct"] = round(p["cost"] / total_cost * 100, 1) if total_cost > 0 else 0.0

    # By model
    model_q = await db.execute(
        select(
            UsageLog.model,
            UsageLog.provider,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.cost_usd), 0).label("avg_cost"),
        ).where(date_filter)
        .group_by(UsageLog.model, UsageLog.provider)
        .order_by(desc("cost"))
    )
    by_model = [
        {
            "model": row.model,
            "provider": row.provider,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "avg_cost": round(float(row.avg_cost), 6),
            "pct": round(float(row.cost) / total_cost * 100, 1) if total_cost > 0 else 0.0,
        }
        for row in model_q
    ]

    # By smart route
    route_q = await db.execute(
        select(
            UsageLog.smart_route_name,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
            func.coalesce(func.avg(UsageLog.cost_usd), 0).label("avg_cost"),
            func.coalesce(func.avg(UsageLog.latency_ms), 0).label("avg_latency"),
        ).where(date_filter, UsageLog.smart_route_name != "")
        .group_by(UsageLog.smart_route_name)
        .order_by(desc("cost"))
    )
    by_smart_route = [
        {
            "smart_route": row.smart_route_name,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "avg_cost": round(float(row.avg_cost), 6),
            "avg_latency": round(float(row.avg_latency)),
            "pct": round(float(row.cost) / total_cost * 100, 1) if total_cost > 0 else 0.0,
        }
        for row in route_q
    ]

    # By service
    svc_q = await db.execute(
        select(
            ApiKey.service,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("tokens"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
        ).join(ApiKey, UsageLog.api_key_id == ApiKey.id)
        .where(date_filter)
        .group_by(ApiKey.service)
        .order_by(desc("cost"))
    )
    by_service = [
        {
            "service": row.service,
            "requests": row.requests,
            "tokens": int(row.tokens),
            "cost": round(float(row.cost), 4),
            "pct": round(float(row.cost) / total_cost * 100, 1) if total_cost > 0 else 0.0,
        }
        for row in svc_q
    ]

    # Daily timeline
    timeline_q = await db.execute(
        select(
            func.date(UsageLog.created_at).label("date"),
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
        ).where(date_filter)
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at))
    )
    daily_timeline = [
        {"date": str(row.date), "requests": row.requests, "cost": round(float(row.cost), 4)}
        for row in timeline_q
    ]

    month_names_es = [
        "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]

    report = {
        "year": year,
        "month": month,
        "month_name": month_names_es[month],
        "period": f"1 - {last_day} de {month_names_es[month]} {year}",
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "summary": summary,
        "by_provider": by_provider,
        "by_model": by_model,
        "by_smart_route": by_smart_route,
        "by_service": by_service,
        "daily_timeline": daily_timeline,
    }

    if format == "pdf":
        html = templates.get_template("admin/report_monthly.html").render(report=report)
        import weasyprint
        pdf_bytes = weasyprint.HTML(string=html).write_pdf()
        filename = f"synapse_estado_cuenta_{year}_{month:02d}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return report


@router.get("/api/reports/available-months")
async def get_available_months(db: AsyncSession = Depends(get_db)):
    """Return list of year-month combos that have usage data."""
    result = await db.execute(
        select(
            func.strftime("%Y", UsageLog.created_at).label("year"),
            func.strftime("%m", UsageLog.created_at).label("month"),
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost_usd), 0).label("cost"),
        )
        .group_by(func.strftime("%Y-%m", UsageLog.created_at))
        .order_by(desc(func.strftime("%Y-%m", UsageLog.created_at)))
    )
    month_names_es = [
        "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    months = []
    for row in result:
        m = int(row.month)
        months.append({
            "year": int(row.year),
            "month": m,
            "label": f"{month_names_es[m]} {row.year}",
            "requests": row.requests,
            "cost": round(float(row.cost), 4),
        })
    return {"months": months}


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
