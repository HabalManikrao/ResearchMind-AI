"""One-off: finish an orphaned research run from its last persisted checkpoint.

A run whose process was killed mid-pipeline is left in RUNNING in SQLite with all
prior stages persisted. This drives just the remaining tail (R&D analysis -> report
-> complete -> knowledge index) against the existing rows, so we don't redo the
~40 min of collection/verification already done.

Usage (backend venv, from backend/, with the backend server STOPPED to avoid
SQLite/Qdrant file-lock contention):
    .venv/Scripts/python salvage_run.py <project_id>
"""
from __future__ import annotations

import asyncio
import sys

from app.database import SessionLocal
from app.llm import get_provider
from app.models import ProjectStatus, ResearchProject
from app.orchestration import orchestrator as orch


async def main(project_id: str) -> None:
    provider = get_provider()

    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None:
            print(f"project {project_id} not found")
            return
        print(f"project: {proj.title!r}  status={proj.status}  progress={proj.progress}%  "
              f"stage={proj.current_stage!r}")

    print("[1/4] R&D analysis (comparison -> recommendation -> delivery plan)...")
    rec_name = await orch._rd_analysis(project_id, provider)
    print(f"      recommendation: {rec_name or '(none)'}")

    print("[2/4] Building report...")
    await orch._build_report(project_id, provider)

    print("[3/4] Marking completed...")
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        proj.status = ProjectStatus.COMPLETED
        proj.progress = 100
        proj.current_stage = "Completed"
        await db.commit()

    print("[4/4] Indexing into knowledge base (best-effort)...")
    await orch._index_knowledge(project_id)

    print("done. run is COMPLETED.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python salvage_run.py <project_id>")
        raise SystemExit(2)
    asyncio.run(main(sys.argv[1]))
