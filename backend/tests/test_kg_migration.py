"""Knowledge-graph migration must be additive, idempotent, non-destructive (#7, spec §31).

The four kg_* tables are created by ``create_all``; no existing table is modified. Simulate
an old-shape DB with research data, run create_all twice, and assert the new tables appear
while existing rows survive.
"""
import tempfile

from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base, _ensure_columns


async def test_kg_migration_additive_idempotent_nondestructive():
    d = tempfile.mkdtemp(prefix="mig7_")
    engine = create_async_engine(f"sqlite+aiosqlite:///{d}/old.db")
    try:
        # OLD schema: a research_projects table with a row, no kg_* tables.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE research_projects "
                "(id TEXT PRIMARY KEY, title TEXT, query TEXT, status TEXT)"
            )
            await conn.exec_driver_sql(
                "INSERT INTO research_projects (id,title,query,status) "
                "VALUES ('p1','Prior','q','completed')"
            )

        from app import models  # noqa: F401  (registers kg_* mappers)

        for _ in range(2):  # run twice — must be idempotent
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await _ensure_columns(conn)

        async with engine.begin() as conn:
            tables = {
                r[0] for r in (
                    await conn.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ).fetchall()
            }
            assert {"kg_entities", "kg_relationships", "kg_mentions", "kg_claim_links"} <= tables

            # Existing research data intact.
            row = (
                await conn.exec_driver_sql(
                    "SELECT title FROM research_projects WHERE id='p1'"
                )
            ).fetchone()
            assert row[0] == "Prior"
    finally:
        await engine.dispose()
