"""In-process pub/sub for live research activity (SSE).

Each project has a set of asyncio subscriber queues. The orchestrator publishes
progress events; the SSE endpoint drains a queue per connected client. This is the
"lean local" stand-in for Redis pub/sub and can be swapped without touching callers.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ProgressEvent:
    project_id: str
    type: str  # e.g. "stage", "activity", "progress", "done", "error"
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, project_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[project_id].add(q)
        return q

    def unsubscribe(self, project_id: str, q: asyncio.Queue) -> None:
        self._subs[project_id].discard(q)
        if not self._subs[project_id]:
            self._subs.pop(project_id, None)

    async def publish(self, event: ProgressEvent) -> None:
        for q in list(self._subs.get(event.project_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # slow consumer: drop rather than block the pipeline


# Singleton bus for the process.
bus = EventBus()
