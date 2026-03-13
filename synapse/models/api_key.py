import datetime
import secrets
from typing import Optional
from sqlalchemy import String, Boolean, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from synapse.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # e.g. "OpenClaw Production"
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(10))  # first chars for identification
    service: Mapped[str] = mapped_column(String(100))  # which service uses this key
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    allowed_models: Mapped[str] = mapped_column(Text, default="*")  # comma-separated or *
    rate_limit_rpm: Mapped[int] = mapped_column(default=60)  # requests per minute
    smart_route_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("smart_routes.id"), nullable=True, default=None
    )  # assigned smart route profile (None = use global)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow
    )

    @staticmethod
    def generate_key() -> str:
        return f"syn-{secrets.token_urlsafe(32)}"
