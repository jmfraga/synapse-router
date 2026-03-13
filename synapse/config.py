from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8800
    secret_key: str = "change-me-to-a-random-string"
    database_url: str = "sqlite+aiosqlite:///./synapse.db"

    # Admin auth
    admin_user: str = "admin"
    admin_password: str = "changeme"

    # Providers
    ollama_base_url: str = "http://localhost:11434"
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    nvidia_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    perplexity_api_key: str = ""

    model_config = {"env_prefix": "SYNAPSE_", "env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
