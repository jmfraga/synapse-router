"""Admin API endpoints for managing providers, routes, and API keys."""

import json
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
from synapse.models import Provider, ApiKey, UsageLog, Route
from synapse.services.auth import hash_key

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="synapse/templates")


# --- Admin UI ---

@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    providers = (await db.execute(select(Provider).order_by(Provider.priority))).scalars().all()
    keys = (await db.execute(select(ApiKey))).scalars().all()
    routes = (await db.execute(select(Route).order_by(Route.priority))).scalars().all()

    # Usage stats
    total_requests = (await db.execute(select(func.count(UsageLog.id)))).scalar() or 0
    total_cost = (await db.execute(select(func.sum(UsageLog.cost_usd)))).scalar() or 0.0
    avg_latency = (await db.execute(select(func.avg(UsageLog.latency_ms)))).scalar() or 0

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "providers": providers,
        "api_keys": keys,
        "routes": routes,
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
    await db.commit()
    # Return raw key only once — it cannot be retrieved after this
    return {"key": raw_key, "id": key.id, "name": key.name}


@router.get("/api/keys")
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey))
    keys = result.scalars().all()
    return [
        {
            "id": k.id, "name": k.name, "key_prefix": k.key_prefix,
            "service": k.service, "is_active": k.is_active,
            "allowed_models": k.allowed_models, "rate_limit_rpm": k.rate_limit_rpm,
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


# --- Metrics ---

@router.get("/api/models")
async def list_available_models():
    """Query Ollama for locally available models."""
    settings = get_settings()
    models = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    models.append(m["name"])
    except Exception:
        pass
    return {"models": sorted(models)}


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
