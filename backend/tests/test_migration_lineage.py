"""The lineage migration must be additive, idempotent, and non-destructive (§28).

Simulates an OLD-shape database (pre-#4) with data, then runs the forward-migration
helpers twice and asserts the new columns exist, existing rows survive, and the
lineage backfill sets root_id — with no error on the second pass.
"""
import tempfile

from sqlalchemy.ext.asyncio import create_async_engine

from app.database import _backfill_lineage, _ensure_columns


async def test_lineage_migration_additive_idempotent_nondestructive():
    d = tempfile.mkdtemp(prefix="mig_")
    engine = create_async_engine(f"sqlite+aiosqlite:///{d}/old.db")
    try:
        # OLD schema: research_projects without lineage columns, claims without confidence_meta.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE research_projects "
                "(id TEXT PRIMARY KEY, title TEXT, query TEXT, status TEXT)"
            )
            await conn.exec_driver_sql(
                "CREATE TABLE claims (id TEXT PRIMARY KEY, project_id TEXT, text TEXT)"
            )
            await conn.exec_driver_sql(
                "INSERT INTO research_projects (id,title,query,status) "
                "VALUES ('p1','Prior work','q','completed')"
            )
            await conn.exec_driver_sql(
                "INSERT INTO claims (id,project_id,text) VALUES ('c1','p1','a claim')"
            )

        # Run the forward migration twice — must be idempotent.
        for _ in range(2):
            async with engine.begin() as conn:
                await _ensure_columns(conn)
                await _backfill_lineage(conn)

        async with engine.begin() as conn:
            cols = {
                r[1]
                for r in (
                    await conn.exec_driver_sql("PRAGMA table_info(research_projects)")
                ).fetchall()
            }
            assert {
                "parent_id", "root_id", "run_number", "run_intent",
                "completed_at", "memory_summary",
                "source_policy",  # Connectivity Intelligence (#5) — additive nullable.
            } <= cols

            ccols = {
                r[1]
                for r in (await conn.exec_driver_sql("PRAGMA table_info(claims)")).fetchall()
            }
            assert "confidence_meta" in ccols

            # Backfill: root_id = own id, run_number defaulted to 1.
            row = (
                await conn.exec_driver_sql(
                    "SELECT root_id, run_number, title FROM research_projects WHERE id='p1'"
                )
            ).fetchone()
            assert row[0] == "p1"
            assert row[1] == 1
            assert row[2] == "Prior work"  # existing data untouched

            # Existing child rows intact.
            n = (await conn.exec_driver_sql("SELECT COUNT(*) FROM claims")).fetchone()[0]
            assert n == 1
    finally:
        await engine.dispose()
