"""Synapse Router — entry point."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from synapse.config import get_settings
from synapse.database import init_db, async_session
from synapse.routers import completions, admin
from synapse.services.seed import seed_providers

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("synapse")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Synapse Router...")
    await init_db()
    async with async_session() as db:
        await seed_providers(db)
    logger.info("Database ready. Providers seeded.")
    yield
    logger.info("Synapse Router shutting down.")


app = FastAPI(
    title="Synapse Router",
    description="Router inteligente de LLMs",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="synapse/static"), name="static")
app.include_router(completions.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


def main():
    settings = get_settings()
    uvicorn.run(
        "synapse.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    main()
