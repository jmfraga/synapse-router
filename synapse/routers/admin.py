"""Admin API endpoints for managing providers, routes, and API keys."""

import asyncio
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.config import get_settings
from synapse.database import get_db
from synapse.models import Provider, ApiKey, UsageLog, Route, SmartRoute
from synapse.services.auth import hash_key

logger = logging.getLogger("synapse.admin")

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="synapse/templates")


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

class ProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None
    max_concurrent: Optional[int] = None


@router.get("/api/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Provider).order_by(Provider.priority))
    providers = result.scalars().all()
    return [
        {
            "id": p.id, "name": p.name, "display_name": p.display_name,
            "base_url": p.base_url, "is_enabled": p.is_enabled,
            "is_local": p.is_local, "priority": p.priority,
            "avg_latency_ms": p.avg_latency_ms,
        }
        for p in providers
    ]


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


# --- Metrics ---

@router.get("/api/models")
async def list_available_models(db: AsyncSession = Depends(get_db)):
    """Query all enabled providers for their available models."""
    settings = get_settings()
    result = await db.execute(
        select(Provider).where(Provider.is_enabled.is_(True)).order_by(Provider.priority)
    )
    providers = result.scalars().all()

    # Known models for providers without a model list API
    KNOWN_MODELS = {
        "anthropic": [
            "claude-opus-4-20250514", "claude-sonnet-4-20250514",
            "claude-haiku-4-5-20251001", "claude-3-5-sonnet-20241022",
        ],
        "perplexity": [
            "sonar-pro", "sonar", "sonar-reasoning-pro", "sonar-reasoning",
        ],
    }

    provider_key_map = {
        "groq": settings.groq_api_key,
        "nvidia": settings.nvidia_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
        "gemini": settings.gemini_api_key,
        "perplexity": settings.perplexity_api_key,
    }

    async def fetch_provider_models(provider: Provider) -> dict:
        """Fetch models for a single provider."""
        name = provider.name
        key = provider_key_map.get(name, "")
        configured = bool(key) or provider.is_local
        models = []

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if name == "ollama":
                    resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                    if resp.status_code == 200:
                        models = [m["name"] for m in resp.json().get("models", [])]

                elif name in KNOWN_MODELS:
                    if configured:
                        models = KNOWN_MODELS[name]

                elif key and name in ("groq", "nvidia", "openai"):
                    # These support the OpenAI-compatible /v1/models endpoint
                    base = provider.base_url or {
                        "groq": "https://api.groq.com/openai/v1",
                        "openai": "https://api.openai.com/v1",
                    }.get(name, "")
                    if base:
                        url = f"{base.rstrip('/')}/models"
                        resp = await client.get(
                            url, headers={"Authorization": f"Bearer {key}"}
                        )
                        if resp.status_code == 200:
                            for m in resp.json().get("data", []):
                                models.append(m["id"])

                elif key and name == "gemini":
                    resp = await client.get(
                        f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                    )
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            # name format: "models/gemini-1.5-flash"
                            model_id = m.get("name", "").replace("models/", "")
                            if model_id:
                                models.append(model_id)
        except Exception as e:
            logger.debug(f"Could not fetch models for {name}: {e}")

        return {
            "provider": name,
            "display_name": provider.display_name,
            "configured": configured,
            "models": sorted(models),
        }

    # Fetch all provider models concurrently
    tasks = [fetch_provider_models(p) for p in providers]
    provider_results = await asyncio.gather(*tasks)

    # Also build flat list for backwards compatibility
    all_models = []
    for pr in provider_results:
        all_models.extend(pr["models"])

    return {
        "models": sorted(set(all_models)),
        "by_provider": provider_results,
    }


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
