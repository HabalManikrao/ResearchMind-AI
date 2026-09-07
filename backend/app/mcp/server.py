"""MCP server core (#8): a dependency-free JSON-RPC 2.0 dispatcher speaking the standard
Model Context Protocol (initialize / tools/list / tools/call / resources). Every handler
calls the capability layer; none touch the DB or duplicate logic (spec §25, §32, §55).

Tested at the protocol layer by driving ``McpServer.handle`` with real MCP messages.
"""
from __future__ import annotations

import json
import os

from app.capabilities.base import CapabilityError, codes, resolve_user
from app.config import get_settings
from app.mcp import tools

PROTOCOL_VERSION = "2024-11-05"
# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
# Bound a single tool result so an agent's context isn't blown (spec §31).
_MAX_RESULT_CHARS = 60000


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _tool_error(mid, code: str, message: str) -> dict:
    """A capability/tool failure is returned as a successful JSON-RPC result with
    ``isError: true`` so the agent sees a structured, machine-readable error (spec §32)."""
    payload = {"error": {"code": code, "message": message}}
    return _result(mid, {
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "isError": True,
    })


def _tool_ok(mid, data: dict) -> dict:
    text = json.dumps(data, default=str)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + "…[truncated]"
    return _result(mid, {"content": [{"type": "text", "text": text}], "structuredContent": data})


class McpServer:
    def __init__(self, token: str | None = None) -> None:
        # Local stdio MCP: the token identifies the acting user. Falls back to the env var,
        # then (when AUTH_ENABLED=false) the shared local user (spec §30 trust model).
        self._token = token if token is not None else os.environ.get("RESEARCHMIND_TOKEN")
        self._user = None

    async def _user_or_error(self):
        if self._user is None:
            self._user = await resolve_user(self._token)  # raises CapabilityError on bad token
        return self._user

    async def handle(self, message: dict) -> dict | None:
        """Handle one JSON-RPC message. Returns a response dict, or None for notifications."""
        if message.get("jsonrpc") != "2.0":
            return _error(message.get("id"), INVALID_REQUEST, "Invalid JSON-RPC version")
        method = message.get("method")
        mid = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return _result(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": get_settings().mcp_server_name, "version": "1.0"},
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None  # notifications get no response
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": [t.spec() for t in tools.TOOLS]})
        if method == "tools/call":
            return await self._tools_call(mid, params)
        if method == "resources/list":
            return _result(mid, {"resources": _resource_catalog()})
        if method == "resources/read":
            return await self._resources_read(mid, params)
        return _error(mid, METHOD_NOT_FOUND, f"Method not found: {method}")

    async def _tools_call(self, mid, params: dict) -> dict:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return _error(mid, INVALID_PARAMS, "tools/call requires a 'name'")
        try:
            user = await self._user_or_error()
            data = await tools.call_tool(user, name, arguments)
        except CapabilityError as e:
            return _tool_error(mid, e.code, e.message)
        except Exception:  # noqa: BLE001 - never leak internals (spec §32)
            return _tool_error(mid, "INTERNAL", "Internal error")
        return _tool_ok(mid, data)

    async def _resources_read(self, mid, params: dict) -> dict:
        uri = params.get("uri", "")
        try:
            user = await self._user_or_error()
            data = await _read_resource(user, uri)
        except CapabilityError as e:
            return _tool_error(mid, e.code, e.message)
        except Exception:  # noqa: BLE001
            return _tool_error(mid, "INTERNAL", "Internal error")
        return _result(mid, {
            "contents": [{"uri": uri, "mimeType": "application/json",
                          "text": json.dumps(data, default=str)[:_MAX_RESULT_CHARS]}]
        })


# --------------------------------------------------------------------------- #
# Resources (read-only URIs — spec §28). Templates, not an enumerable list.
# --------------------------------------------------------------------------- #
def _resource_catalog() -> list[dict]:
    return [
        {"uri": "research://{id}", "name": "Research report", "mimeType": "application/json"},
        {"uri": "research://{id}/claims", "name": "Research claims", "mimeType": "application/json"},
        {"uri": "knowledge://entity/{id}", "name": "Knowledge entity", "mimeType": "application/json"},
        {"uri": "knowledge://entity/{id}/history", "name": "Entity history", "mimeType": "application/json"},
    ]


async def _read_resource(user, uri: str) -> dict:
    from app.capabilities import knowledge as cap_kg
    from app.capabilities import research as cap_research

    if uri.startswith("research://"):
        rest = uri[len("research://"):]
        parts = rest.split("/")
        rid = parts[0]
        if len(parts) == 1:
            return await cap_research.report(user, rid, excerpt=True)
        if parts[1] == "claims":
            return await cap_research.claims(user, rid)
    elif uri.startswith("knowledge://entity/"):
        rest = uri[len("knowledge://entity/"):]
        parts = rest.split("/")
        eid = parts[0]
        if len(parts) == 1:
            return await cap_kg.entity(user, eid)
        if parts[1] == "history":
            return await cap_kg.entity_history(user, eid)
    raise CapabilityError(codes.NOT_FOUND, f"Unknown resource URI: {uri}", 404)
