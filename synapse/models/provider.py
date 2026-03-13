import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from synapse.database import Base


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)  # ollama, anthropic, groq, etc.
    display_name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_env: Mapped[str] = mapped_column(String(100), default="")  # env var name for API key
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=10)  # lower = higher priority
    max_concurrent: Mapped[int] = mapped_column(Integer, default=10)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # tracked automatically
    config_json: Mapped[str] = mapped_column(Text, default="{}")  # extra provider-specific config
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
