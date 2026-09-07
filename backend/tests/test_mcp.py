"""MCP adapter (#8, spec §44, §46, §51): tests the ACTUAL protocol — initialize, tools/list,
tools/call, resources, error mapping, auth, bounded output, offline, and REST↔MCP parity."""
import json

import pytest

import app.services.connectivity as conn
from app.mcp.server import METHOD_NOT_FOUND, McpServer
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from tests.conftest import run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(overall=ONLINE, internet=True, search_provider=True,
                                    ollama=True, qdrant=True, database=True)
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


def _token(client) -> str:
    return client.headers["Authorization"].split(" ", 1)[1]


def _server(client) -> McpServer:
    return McpServer(token=_token(client))


async def _rpc(server, method, params=None, mid=1):
    return await server.handle({"jsonrpc": "2.0", "id": mid, "method": method,
                                "params": params or {}})


async def _call(server, name, arguments=None, mid=1):
    resp = await _rpc(server, "tools/call", {"name": name, "arguments": arguments or {}}, mid)
    return resp["result"]


def _payload(result: dict) -> dict:
    """The JSON payload inside a tool result's text content."""
    return json.loads(result["content"][0]["text"])


async def _complete(client, query="best vector db"):
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    return pid


# --------------------------------------------------------------------------- #
# Protocol: initialize / tools discovery
# --------------------------------------------------------------------------- #
async def test_initialize(client):
    resp = await _rpc(_server(client), "initialize")
    r = resp["result"]
    assert r["protocolVersion"] and r["serverInfo"]["name"]
    assert "tools" in r["capabilities"]


async def test_tools_list_discovery(client):
    resp = await _rpc(_server(client), "tools/list")
    tools = resp["result"]["tools"]
    assert len(tools) >= 15
    for t in tools:
        assert t["name"] and t["description"] and t["inputSchema"]["type"] == "object"


async def test_method_not_found(client):
    resp = await _rpc(_server(client), "does/not/exist")
    assert resp["error"]["code"] == METHOD_NOT_FOUND


# --------------------------------------------------------------------------- #
# tools/call: success + bounded structured output
# --------------------------------------------------------------------------- #
async def test_tool_call_success_and_structured(client):
    result = await _call(_server(client), "system_connectivity")
    assert result.get("isError") is not True
    assert "structuredContent" in result
    assert _payload(result)["overall_status"] == "online"


async def test_report_tool_is_bounded_excerpt(client, patch_pipeline):
    pid = await _complete(client)
    result = await _call(_server(client), "research_report", {"research_id": pid})
    payload = _payload(result)
    assert payload["research_id"] == pid
    # Report is an excerpt by default for agent context (spec §29, §31).
    assert len(payload["markdown"]) <= 4100


# --------------------------------------------------------------------------- #
# Error mapping (spec §32)
# --------------------------------------------------------------------------- #
async def test_missing_resource_maps_to_tool_error(client):
    result = await _call(_server(client), "research_status", {"research_id": "nope"})
    assert result["isError"] is True
    assert _payload(result)["error"]["code"] == "RESEARCH_NOT_FOUND"


async def test_invalid_arguments_map_to_error(client):
    # Missing required arg.
    r1 = await _call(_server(client), "research_status", {})
    assert r1["isError"] and _payload(r1)["error"]["code"] == "INVALID_ARGUMENT"
    # Unknown argument.
    r2 = await _call(_server(client), "system_connectivity", {"bogus": 1})
    assert r2["isError"] and _payload(r2)["error"]["code"] == "INVALID_ARGUMENT"
    # Unknown tool.
    r3 = await _call(_server(client), "no_such_tool", {})
    assert r3["isError"] and _payload(r3)["error"]["code"] == "INVALID_ARGUMENT"


async def test_unauthorized_token_is_denied(client):
    bad = McpServer(token="not-a-valid-jwt")
    result = await _call(bad, "system_connectivity")
    assert result["isError"] and _payload(result)["error"]["code"] == "ACCESS_DENIED"


# --------------------------------------------------------------------------- #
# Long-running research: returns quickly with an id, not a blocking report (spec §22)
# --------------------------------------------------------------------------- #
async def test_research_start_is_non_blocking(client, patch_pipeline):
    result = await _call(_server(client), "research_start",
                         {"query": "mcp long running research topic"})
    assert result.get("isError") is not True
    rid = _payload(result)["research_id"]
    assert rid
    await run_to_completion(rid, timeout=60)


# --------------------------------------------------------------------------- #
# Offline / local (spec §46): knowledge search needs no network
# --------------------------------------------------------------------------- #
async def test_knowledge_search_offline(client, patch_pipeline):
    await _complete(client)
    result = await _call(_server(client), "knowledge_search", {})
    assert result.get("isError") is not True
    assert "entities" in _payload(result)


# --------------------------------------------------------------------------- #
# Resources
# --------------------------------------------------------------------------- #
async def test_resources_list_and_read(client, patch_pipeline):
    server = _server(client)
    lst = await _rpc(server, "resources/list")
    assert any(r["uri"].startswith("research://") for r in lst["result"]["resources"])

    pid = await _complete(client)
    read = await _rpc(server, "resources/read", {"uri": f"research://{pid}"})
    contents = read["result"]["contents"][0]
    assert json.loads(contents["text"])["research_id"] == pid


# --------------------------------------------------------------------------- #
# Compatibility: REST and MCP exercise the SAME capability (spec §51, §55)
# --------------------------------------------------------------------------- #
async def test_rest_and_mcp_equivalent(client, patch_pipeline):
    pid = await _complete(client)
    rest = (await client.get(f"/v1/research/{pid}/claims")).json()
    mcp = _payload(await _call(_server(client), "research_claims", {"research_id": pid}))
    assert rest["total"] == mcp["total"]
    assert [c["claim_id"] for c in rest["claims"]] == [c["claim_id"] for c in mcp["claims"]]
