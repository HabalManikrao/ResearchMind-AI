"""Manages background research runs and their pause/resume/cancel controls."""
from __future__ import annotations

import asyncio

from app.orchestration.control import RunControl
from app.orchestration.orchestrator import run_research


class RunManager:
    def __init__(self) -> None:
        self._controls: dict[str, RunControl] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def is_active(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        return task is not None and not task.done()

    def active_ids(self) -> list[str]:
        return [pid for pid, t in self._tasks.items() if not t.done()]

    def start(self, project_id: str) -> bool:
        if self.is_active(project_id):
            return False
        control = RunControl()
        self._controls[project_id] = control
        task = asyncio.create_task(self._run(project_id, control))
        self._tasks[project_id] = task
        return True

    async def _run(self, project_id: str, control: RunControl) -> None:
        try:
            await run_research(project_id, control)
        finally:
            self._controls.pop(project_id, None)
            self._tasks.pop(project_id, None)

    def pause(self, project_id: str) -> bool:
        c = self._controls.get(project_id)
        if c and not c.is_paused:
            c.pause()
            return True
        return False

    def resume(self, project_id: str) -> bool:
        c = self._controls.get(project_id)
        if c and c.is_paused:
            c.resume()
            return True
        return False

    def stop(self, project_id: str) -> bool:
        c = self._controls.get(project_id)
        if c:
            c.cancel()
            return True
        return False


manager = RunManager()
