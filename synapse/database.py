import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from synapse.config import get_settings

logger = logging.getLogger("synapse.database")


class Base(DeclarativeBase):
    pass


engine = create_async_engine(get_settings().database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Migrations: add columns that create_all won't add to existing tables
_MIGRATIONS = [
    ("usage_logs", "smart_route_name", "VARCHAR(100) DEFAULT ''"),
    ("usage_logs", "intent", "VARCHAR(50) DEFAULT ''"),
]


async def _run_migrations(conn):
    """Add missing columns to existing tables (idempotent)."""
    for table, column, col_type in _MIGRATIONS:
        try:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            ))
            logger.info(f"Migration: added {table}.{column}")
        except Exception:
            pass  # column already exists


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def get_db():
    async with async_session() as session:
        yield session
