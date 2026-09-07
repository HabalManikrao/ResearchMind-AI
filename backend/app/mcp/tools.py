"""MCP tool registry (#8). Each tool is a thin binding from a strict input schema to a
capability function — the single implementation (spec §26, §27). No tool touches the DB or
reimplements research/evidence/graph logic."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.capabilities import documents as cap_docs
from app.capabilities import knowledge as cap_kg
from app.capabilities import monitoring as cap_mon
from app.capabilities import research as cap_research
from app.capabilities import system as cap_system
from app.capabilities.base import CapabilityError, codes

Handler = Callable[[Any, dict], Awaitable[dict]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Handler

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _require(args: dict, *keys: str) -> None:
    for k in keys:
        if args.get(k) in (None, ""):
            raise CapabilityError(codes.INVALID_ARGUMENT, f"'{k}' is required")


def _reject_unknown(args: dict, schema: dict) -> None:
    allowed = set(schema.get("properties", {}))
    extra = set(args) - allowed
    if extra:
        raise CapabilityError(codes.INVALID_ARGUMENT, f"unknown argument(s): {sorted(extra)}")


_STR = {"type": "string"}
_INT = {"type": "integer"}
_STRLIST = {"type": "array", "items": {"type": "string"}}


# --------------------------------------------------------------------------- #
# Handlers (bounded; excerpt reports by default for agent context — spec §29, §31)
# --------------------------------------------------------------------------- #
async def _research_search(user, a):
    return await cap_research.search(user, q=a.get("q"), limit=a.get("limit"), offset=a.get("offset"))


async def _research_start(user, a):
    _require(a, "query")
    return await cap_research.start(
        user, query=a["query"], sources_enabled=a.get("sources_enabled"),
        mode=a.get("mode", "deep"), source_policy=a.get("source_policy"),
        idempotency_key=a.get("idempotency_key"),
    )


async def _research_status(user, a):
    _require(a, "research_id")
    return await cap_research.status(user, a["research_id"])


async def _research_report(user, a):
    _require(a, "research_id")
    return await cap_research.report(user, a["research_id"], excerpt=a.get("excerpt", True))


async def _research_claims(user, a):
    _require(a, "research_id")
    return await cap_research.claims(user, a["research_id"], limit=a.get("limit"), offset=a.get("offset"))


async def _research_evidence(user, a):
    _require(a, "research_id", "claim_id")
    return await cap_research.evidence(user, a["research_id"], a["claim_id"])


async def _research_again(user, a):
    _require(a, "research_id")
    return await cap_research.again(
        user, a["research_id"], intent=a.get("intent", "refresh"),
        sources_enabled=a.get("sources_enabled"), idempotency_key=a.get("idempotency_key"),
    )


async def _research_diff(user, a):
    _require(a, "research_id", "other_id")
    return await cap_research.diff(user, a["research_id"], a["other_id"])


async def _document_search(user, a):
    _require(a, "project_id", "query")
    return await cap_docs.search(user, a["project_id"], a["query"], top_k=a.get("top_k"))


async def _knowledge_search(user, a):
    return await cap_kg.entity_search(user, q=a.get("q"), type=a.get("type"),
                                      limit=a.get("limit"), offset=a.get("offset"))


async def _knowledge_entity(user, a):
    _require(a, "entity_id")
    return await cap_kg.entity(user, a["entity_id"])


async def _knowledge_graph(user, a):
    _require(a, "entity_id")
    return await cap_kg.graph(user, a["entity_id"], depth=a.get("depth", 1))


async def _monitor_status(user, a):
    _require(a, "project_id")
    return await cap_mon.status(user, a["project_id"])


async def _monitor_changes(user, a):
    _require(a, "project_id")
    return await cap_mon.changes(user, a["project_id"])


async def _system_connectivity(user, a):
    return await cap_system.connectivity(user)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
TOOLS: list[Tool] = [
    Tool("research_search", "Search prior research projects by keyword.",
         _schema({"q": _STR, "limit": _INT, "offset": _INT}), _research_search),
    Tool("research_start", "Start a new research run (returns immediately; runs in the background).",
         _schema({"query": _STR, "sources_enabled": _STRLIST, "mode": _STR,
                  "source_policy": _STR, "idempotency_key": _STR}, ["query"]), _research_start),
    Tool("research_status", "Get a research run's status, progress, connectivity and health.",
         _schema({"research_id": _STR}, ["research_id"]), _research_status),
    Tool("research_report", "Get a completed run's report (bounded excerpt + metadata).",
         _schema({"research_id": _STR, "excerpt": {"type": "boolean"}}, ["research_id"]), _research_report),
    Tool("research_claims", "List a run's claims with confidence and evidence counts.",
         _schema({"research_id": _STR, "limit": _INT, "offset": _INT}, ["research_id"]), _research_claims),
    Tool("research_evidence", "Get supporting/contradicting evidence for a claim (with provenance).",
         _schema({"research_id": _STR, "claim_id": _STR}, ["research_id", "claim_id"]), _research_evidence),
    Tool("research_again", "Continue a completed run (refresh/deepen/verify/full) as a new linked run.",
         _schema({"research_id": _STR, "intent": _STR, "sources_enabled": _STRLIST,
                  "idempotency_key": _STR}, ["research_id"]), _research_again),
    Tool("research_diff", "Deterministically diff two runs in the same lineage.",
         _schema({"research_id": _STR, "other_id": _STR}, ["research_id", "other_id"]), _research_diff),
    Tool("document_search", "Semantic search over a project's uploaded documents.",
         _schema({"project_id": _STR, "query": _STR, "top_k": _INT}, ["project_id", "query"]), _document_search),
    Tool("knowledge_search", "Search knowledge-graph entities by name/alias/type.",
         _schema({"q": _STR, "type": _STR, "limit": _INT, "offset": _INT}), _knowledge_search),
    Tool("knowledge_entity", "Get a knowledge-graph entity's detail and related entities.",
         _schema({"entity_id": _STR}, ["entity_id"]), _knowledge_entity),
    Tool("knowledge_graph", "Get a bounded entity neighbourhood (depth-clamped).",
         _schema({"entity_id": _STR, "depth": _INT}, ["entity_id"]), _knowledge_graph),
    Tool("monitor_status", "Get a research lineage's monitor configuration and health.",
         _schema({"project_id": _STR}, ["project_id"]), _monitor_status),
    Tool("monitor_changes", "List a monitor's recent checks and meaningful changes.",
         _schema({"project_id": _STR}, ["project_id"]), _monitor_changes),
    Tool("system_connectivity", "Current live/cached/local connectivity and research mode.",
         _schema({}), _system_connectivity),
]

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in TOOLS}


async def call_tool(user, name: str, arguments: dict) -> dict:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        raise CapabilityError(codes.INVALID_ARGUMENT, f"Unknown tool: {name}")
    args = arguments or {}
    _reject_unknown(args, tool.input_schema)
    return await tool.handler(user, args)
