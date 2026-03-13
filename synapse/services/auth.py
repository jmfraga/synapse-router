"""API key authentication and management."""

import hashlib
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.database import get_db
from synapse.models import ApiKey


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def authenticate(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Validate Bearer token and return the associated API key record."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization format")

    token = authorization.removeprefix("Bearer ").strip()
    key_hash = hash_key(token)

    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    return api_key
