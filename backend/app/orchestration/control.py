"""Per-run control handles for pause/resume/cancel (spec §12, rule §23.12)."""
from __future__ import annotations

import asyncio


class Cancelled(Exception):
    """Raised inside the pipeline when a run is cancelled/stopped."""


class RunControl:
    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()  # start in the running state
        self._cancelled = False

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._running.set()  # unblock any paused waiters so they can observe cancel

    @property
    def is_paused(self) -> bool:
        return not self._running.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def checkpoint(self) -> None:
        """Await if paused; raise if cancelled. Call at stage boundaries."""
        if self._cancelled:
            raise Cancelled()
        await self._running.wait()
        if self._cancelled:
            raise Cancelled()
