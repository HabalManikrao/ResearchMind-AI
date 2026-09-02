"""Async SQLAlchemy engine, session factory, and Base."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped session."""
    async with SessionLocal() as session:
        yield session


# Columns added to already-existing tables after their first release. `create_all`
# creates missing *tables* but never adds *columns*, so on an existing dev SQLite
# DB these are applied by a tiny idempotent ALTER (no Alembic yet). Keep in sync
# when adding a nullable column to a pre-existing model.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "claims": {"confidence_meta": "TEXT"},
    # Research lineage (#4). All nullable/defaulted so existing rows are valid.
    "research_projects": {
        "parent_id": "TEXT",
        "root_id": "TEXT",
        "run_number": "INTEGER DEFAULT 1",
        "run_intent": "TEXT",
        "completed_at": "TIMESTAMP",
        "memory_summary": "TEXT",
        # Connectivity Intelligence (#5): live/cached/local sourcing policy.
        "source_policy": "TEXT",
    },
    # Research monitoring (#6): notifications gain impact + a diff link. All nullable so
    # existing notifications remain valid; research_monitors/monitor_checks are new
    # tables created by create_all (no ALTER needed).
    "notifications": {
        "severity": "TEXT",
        "monitor_id": "TEXT",
        "dedup_key": "TEXT",
        "data": "TEXT",
    },
}


async def _ensure_columns(conn) -> None:
    """Lightweight, SQLite-only forward migration for columns added to existing
    tables. Safe to run on every startup: it only adds columns that are missing."""
    if conn.dialect.name != "sqlite":
        return  # Postgres path will use real migrations when it lands.
    for table, cols in _ADDED_COLUMNS.items():
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in result.fetchall()}
        if not existing:
            continue  # table absent -> create_all made it fresh with all columns
        for col, coltype in cols.items():
            if col not in existing:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"
                )


async def _backfill_lineage(conn) -> None:
    """Idempotent: give pre-#4 projects a single-run lineage (root_id = own id).
    A no-op once every row has a root_id."""
    if conn.dialect.name != "sqlite":
        return
    result = await conn.exec_driver_sql("PRAGMA table_info(research_projects)")
    cols = {row[1] for row in result.fetchall()}
    if "root_id" not in cols:
        return  # table absent or freshly created with all columns via create_all
    await conn.exec_driver_sql(
        "UPDATE research_projects SET root_id = id WHERE root_id IS NULL"
    )


async def init_db() -> None:
    """Create all tables. Import models first so they register on Base.metadata."""
    from app import models  # noqa: F401  (registers mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _backfill_lineage(conn)
