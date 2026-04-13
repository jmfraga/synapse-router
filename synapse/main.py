"""Synapse Router — entry point."""

import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from synapse.config import get_settings
from synapse.database import init_db, async_session
from synapse.routers import completions, admin, audio
from synapse.services.seed import seed_providers
from synapse.services.litellm_router import build_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("synapse")

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Synapse Router...")
    await init_db()
    async with async_session() as db:
        await seed_providers(db)
        await build_router(db)
    logger.info("Database ready. Providers seeded. litellm Router initialized.")
    yield
    logger.info("Synapse Router shutting down.")


app = FastAPI(
    title="Synapse Router",
    description="Router inteligente de LLMs",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="synapse/static"), name="static")
app.include_router(completions.router)
app.include_router(audio.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0", "uptime_s": int(time.time() - _start_time)}


@app.get("/metrics")
async def metrics():
    """Real-time metrics for Synapse Router monitoring."""
    async with async_session() as db:
        # Per-route metrics (last 1h)
        routes_q = await db.execute(text("""
            SELECT smart_route_name, intent, provider, model,
                   COUNT(*) as requests,
                   ROUND(AVG(latency_ms)) as avg_latency_ms,
                   MIN(latency_ms) as min_ms,
                   MAX(latency_ms) as max_ms,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status<>'success' THEN 1 ELSE 0 END) as errors
            FROM usage_logs
            WHERE created_at >= datetime('now', '-1 hour')
              AND smart_route_name <> ''
            GROUP BY smart_route_name, intent, provider, model
            ORDER BY smart_route_name, requests DESC
        """))
        routes = [dict(r._mapping) for r in routes_q.fetchall()]

        # Global summary (last 1h)
        summary_q = await db.execute(text("""
            SELECT COUNT(*) as total_requests,
                   ROUND(AVG(latency_ms)) as avg_latency_ms,
                   SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status<>'success' THEN 1 ELSE 0 END) as errors
            FROM usage_logs
            WHERE created_at >= datetime('now', '-1 hour')
        """))
        summary = dict(summary_q.fetchone()._mapping)

        # Per-route health (last 1h): success rate + avg latency
        health_q = await db.execute(text("""
            SELECT smart_route_name,
                   COUNT(*) as requests,
                   ROUND(AVG(latency_ms)) as avg_latency_ms,
                   ROUND(100.0 * SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
            FROM usage_logs
            WHERE created_at >= datetime('now', '-1 hour')
              AND smart_route_name <> ''
            GROUP BY smart_route_name
            ORDER BY success_rate ASC
        """))
        health = [dict(r._mapping) for r in health_q.fetchall()]

        # Active routes count
        active_q = await db.execute(text(
            "SELECT COUNT(*) FROM smart_routes WHERE is_enabled=1"
        ))
        active_routes = active_q.scalar()

    return {
        "uptime_s": int(time.time() - _start_time),
        "active_routes": active_routes,
        "window": "1h",
        "summary": summary,
        "route_health": health,
        "route_details": routes,
    }


def main():
    import os
    settings = get_settings()
    uvicorn.run(
        "synapse.main:app",
        host=settings.host,
        port=settings.port,
        reload=os.environ.get("SYNAPSE_DEV", "") == "1",
    )


if __name__ == "__main__":
    main()
