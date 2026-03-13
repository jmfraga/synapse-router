"""Seed default providers on first run."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.models import Provider

DEFAULT_PROVIDERS = [
    {
        "name": "ollama",
        "display_name": "Ollama (Local)",
        "base_url": "http://localhost:11434",
        "api_key_env": "",
        "is_local": True,
        "priority": 1,
    },
    {
        "name": "groq",
        "display_name": "Groq",
        "base_url": "",
        "api_key_env": "SYNAPSE_GROQ_API_KEY",
        "is_local": False,
        "priority": 2,
    },
    {
        "name": "nvidia",
        "display_name": "Nvidia NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "SYNAPSE_NVIDIA_API_KEY",
        "is_local": False,
        "priority": 3,
    },
    {
        "name": "anthropic",
        "display_name": "Anthropic",
        "base_url": "",
        "api_key_env": "SYNAPSE_ANTHROPIC_API_KEY",
        "is_local": False,
        "priority": 4,
    },
    {
        "name": "openai",
        "display_name": "OpenAI",
        "base_url": "",
        "api_key_env": "SYNAPSE_OPENAI_API_KEY",
        "is_local": False,
        "priority": 5,
    },
    {
        "name": "gemini",
        "display_name": "Google Gemini",
        "base_url": "",
        "api_key_env": "SYNAPSE_GEMINI_API_KEY",
        "is_local": False,
        "priority": 6,
    },
    {
        "name": "perplexity",
        "display_name": "Perplexity",
        "base_url": "",
        "api_key_env": "SYNAPSE_PERPLEXITY_API_KEY",
        "is_local": False,
        "priority": 7,
    },
]


async def seed_providers(db: AsyncSession):
    """Insert default providers if table is empty."""
    result = await db.execute(select(Provider).limit(1))
    if result.scalar_one_or_none() is not None:
        return  # already seeded

    for p in DEFAULT_PROVIDERS:
        db.add(Provider(**p))
    await db.commit()
