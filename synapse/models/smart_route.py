import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from synapse.database import Base


class SmartRoute(Base):
    __tablename__ = "smart_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "openclaw-smart"
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_model: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "auto"
    classifier_model: Mapped[str] = mapped_column(String(100))  # e.g. "llama3.1:8b"
    classifier_prompt: Mapped[str] = mapped_column(Text, default="")  # auto-generated if empty
    intents_json: Mapped[str] = mapped_column(Text, default="[]")
    default_chain_json: Mapped[str] = mapped_column(Text, default="[]")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
