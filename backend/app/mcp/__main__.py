"""MCP stdio entrypoint (#8): ``python -m app.mcp``.

Reads newline-delimited JSON-RPC messages from stdin and writes responses to stdout — the
standard MCP stdio transport. Auth via the ``RESEARCHMIND_TOKEN`` env var (or the shared
local user when ``AUTH_ENABLED=false``). Purely stdlib; no external MCP dependency.
"""
from __future__ import annotations

import asyncio
import json
import sys

from app.mcp.server import PARSE_ERROR, McpServer, _error


async def _serve() -> None:
    server = McpServer()
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:  # EOF — client closed the pipe
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(_error(None, PARSE_ERROR, "Parse error"))
            continue
        try:
            response = await server.handle(message)
        except Exception:  # noqa: BLE001 - a bad message must not kill the loop
            response = _error(message.get("id") if isinstance(message, dict) else None,
                              -32603, "Internal error")
        if response is not None:
            _write(response)


def _write(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass
