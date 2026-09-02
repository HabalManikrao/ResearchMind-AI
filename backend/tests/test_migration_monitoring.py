"""Monitoring migration must be additive, idempotent, and non-destructive (#6, spec §38).

Simulates an OLD-shape database (pre-#6): a ``notifications`` table without the monitoring
columns and no monitor tables, with data. Runs the forward migration (create_all +
_ensure_columns) twice and asserts the new columns/tables appear, existing rows survive,
and the second pass is a no-op.
"""
import tempfile

from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base, _ensure_columns


async def test_monitoring_migration_additive_idempotent_nondestructive():
    d = tempfile.mkdtemp(prefix="mig6_")
    engine = create_async_engine(f"sqlite+aiosqlite:///{d}/old.db")
    try:
        # OLD schema: a notifications table without the #6 columns, plus a row.
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE notifications "
                "(id TEXT PRIMARY KEY, user_id TEXT, type TEXT, title TEXT, "
                " message TEXT, project_id TEXT, read BOOLEAN, created_at TIMESTAMP)"
            )
            await conn.exec_driver_sql(
                "INSERT INTO notifications (id,user_id,type,title,message,read) "
                "VALUES ('n1','u1','research_completed','Done','ok',0)"
            )

        # Forward migration twice — must be idempotent.
        from app import models  # noqa: F401  (register mappers, incl. #6 tables)

        for _ in range(2):
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)  # creates new tables only
                await _ensure_columns(conn)                    # adds notification columns

        async with engine.begin() as conn:
            ncols = {
                r[1]
                for r in (
                    await conn.exec_driver_sql("PRAGMA table_info(notifications)")
                ).fetchall()
            }
            assert {"severity", "monitor_id", "dedup_key", "data"} <= ncols

            tables = {
                r[0]
                for r in (
                    await conn.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                ).fetchall()
            }
            assert "research_monitors" in tables
            assert "monitor_checks" in tables

            # Existing notification row intact and its new columns default to NULL.
            row = (
                await conn.exec_driver_sql(
                    "SELECT title, severity, monitor_id FROM notifications WHERE id='n1'"
                )
            ).fetchone()
            assert row[0] == "Done"       # existing data untouched
            assert row[1] is None         # additive columns are nullable
            assert row[2] is None
    finally:
        await engine.dispose()
