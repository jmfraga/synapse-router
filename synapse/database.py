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


async def _migrate_smart_route_ids(conn):
    """One-time migration: copy api_keys.smart_route_id → junction table."""
    try:
        await conn.execute(text(
            "INSERT OR IGNORE INTO api_key_smart_routes (api_key_id, smart_route_id) "
            "SELECT id, smart_route_id FROM api_keys "
            "WHERE smart_route_id IS NOT NULL"
        ))
        logger.info("Migration: smart_route_id → api_key_smart_routes (done or no-op)")
    except Exception:
        pass  # table doesn't exist yet or already migrated


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
        await _migrate_smart_route_ids(conn)


async def get_db():
    async with async_session() as session:
        yield session
