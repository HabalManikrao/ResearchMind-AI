"""Capability-layer foundations (#8): error model, auth resolution, ownership, registry,
idempotency. Shared by every capability and both adapters (REST /v1, MCP)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.config import get_settings
from app.database import SessionLocal
from app.models import ResearchProject, User
from app.security.auth import _local_user, decode_token


# --------------------------------------------------------------------------- #
# Error model (stable, machine-readable — spec §20, §32)
# --------------------------------------------------------------------------- #
class codes:
    RESEARCH_NOT_FOUND = "RESEARCH_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    RESEARCH_IN_PROGRESS = "RESEARCH_IN_PROGRESS"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    CONNECTIVITY_DEGRADED = "CONNECTIVITY_DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"


class CapabilityError(Exception):
    """A transport-agnostic capability error. Adapters map ``code``/``http_status`` to their
    own envelope (REST JSON, MCP tool error). Never carries stack traces or secrets."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# --------------------------------------------------------------------------- #
# Auth resolution (mirrors get_current_user; usable without an HTTP request — MCP)
# --------------------------------------------------------------------------- #
async def resolve_user(token: str | None) -> User:
    """Resolve the acting user from a bearer token (or the shared local user when auth is
    disabled). Used by MCP, which has no FastAPI request. REST reuses get_current_user."""
    settings = get_settings()
    if not settings.auth_enabled:
        return _local_user()
    if not token:
        raise CapabilityError(codes.ACCESS_DENIED, "Authentication required", 401)
    try:
        user_id = decode_token(token)
    except HTTPException:
        raise CapabilityError(codes.ACCESS_DENIED, "Invalid or expired token", 401)
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise CapabilityError(codes.ACCESS_DENIED, "Invalid or expired token", 401)
    return user


# --------------------------------------------------------------------------- #
# Ownership (reuses the same rule as research._get_project — spec §37)
# --------------------------------------------------------------------------- #
def map_http_error(exc: HTTPException) -> CapabilityError:
    """Convert an internal HTTPException (from a reused API/service helper) into the stable
    capability error contract — so capabilities never leak framework-specific errors."""
    mapping = {
        401: codes.ACCESS_DENIED, 403: codes.ACCESS_DENIED, 404: codes.NOT_FOUND,
        409: codes.RESEARCH_IN_PROGRESS, 422: codes.INVALID_ARGUMENT, 429: codes.RATE_LIMITED,
    }
    code = mapping.get(exc.status_code, codes.INVALID_ARGUMENT)
    return CapabilityError(code, str(exc.detail), exc.status_code)


async def owned_project(db, project_id: str, user: User) -> ResearchProject:
    """Fetch a project the user may access (own or legacy/unowned). 404 (not 403) so
    existence isn't leaked — identical to the internal API rule."""
    proj = await db.get(ResearchProject, project_id)
    if proj is None or (proj.user_id is not None and proj.user_id != user.id):
        raise CapabilityError(codes.RESEARCH_NOT_FOUND, "Research project not found", 404)
    return proj


def clamp_page(limit: int | None, offset: int | None) -> tuple[int, int]:
    s = get_settings()
    # Floor at 1: a negative limit must never reach the DB (SQLite treats LIMIT -1 as
    # UNBOUNDED, so an external client passing ?limit=-1 would bypass the page cap and pull
    # the whole table — a pagination-abuse/DoS vector, spec §26/§49).
    lim = min(max(int(limit) if limit else s.capability_page_size, 1), s.capability_max_page_size)
    off = max(int(offset) if offset else 0, 0)
    return lim, off


# --------------------------------------------------------------------------- #
# Idempotency (in-memory, bounded, TTL — spec §23, §48: no migration)
# --------------------------------------------------------------------------- #
_IDEMPOTENCY: dict[tuple[str, str], tuple[float, Any]] = {}
_IDEMPOTENCY_MAX = 2000


def _prune_idempotency(now: float) -> None:
    expired = [k for k, (exp, _) in _IDEMPOTENCY.items() if exp < now]
    for k in expired:
        _IDEMPOTENCY.pop(k, None)
    # Hard cap: drop oldest if we somehow exceed the bound.
    if len(_IDEMPOTENCY) > _IDEMPOTENCY_MAX:
        for k in sorted(_IDEMPOTENCY, key=lambda k: _IDEMPOTENCY[k][0])[:200]:
            _IDEMPOTENCY.pop(k, None)


def idempotency_get(user_id: str, key: str) -> Any | None:
    if not key:
        return None
    now = time.monotonic()
    _prune_idempotency(now)
    entry = _IDEMPOTENCY.get((user_id, key))
    return entry[1] if entry else None


def idempotency_put(user_id: str, key: str, result: Any) -> None:
    if not key:
        return
    ttl = get_settings().idempotency_ttl_seconds
    _IDEMPOTENCY[(user_id, key)] = (time.monotonic() + ttl, result)


# --------------------------------------------------------------------------- #
# Capability registry (discovery — spec §34, §35)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Capability:
    name: str
    group: str
    description: str
    requires_network: bool = False   # may need live internet (external research)
    may_invoke_llm: bool = False     # may call Ollama (planning/verification/embeddings)
    long_running: bool = False       # returns quickly but starts background work
    mutating: bool = False           # changes state


REGISTRY: list[Capability] = [
    Capability("research_search", "research", "Search prior research projects by keyword."),
    Capability("research_start", "research", "Start a new research run (returns immediately; runs in the background).",
               requires_network=True, may_invoke_llm=True, long_running=True, mutating=True),
    Capability("research_status", "research", "Get a research run's status, progress, connectivity and health."),
    Capability("research_report", "research", "Get a completed run's report (bounded excerpt + metadata)."),
    Capability("research_claims", "research", "List a run's verified claims with confidence and evidence counts."),
    Capability("research_evidence", "research", "Get the supporting/contradicting evidence for a claim (with provenance)."),
    Capability("research_again", "research", "Continue a completed run (refresh/deepen/verify/full) as a new linked run.",
               requires_network=True, may_invoke_llm=True, long_running=True, mutating=True),
    Capability("research_diff", "research", "Deterministically diff two runs in the same lineage."),
    Capability("document_search", "documents", "Semantic search over a project's uploaded documents.", may_invoke_llm=True),
    Capability("document_list", "documents", "List a project's uploaded documents and their status."),
    Capability("knowledge_search", "knowledge", "Search knowledge-graph entities by name/alias/type."),
    Capability("knowledge_entity", "knowledge", "Get an entity's detail, related entities and counts."),
    Capability("knowledge_graph", "knowledge", "Get a bounded entity neighbourhood (depth-clamped)."),
    Capability("knowledge_entity_claims", "knowledge", "List an entity's current or historical claims."),
    Capability("knowledge_entity_history", "knowledge", "Get an entity's observation + supersession history."),
    Capability("monitor_status", "monitoring", "Get a research lineage's monitor configuration and health."),
    Capability("monitor_changes", "monitoring", "List a monitor's recent checks and meaningful changes."),
    Capability("system_connectivity", "system", "Current live/cached/local connectivity and research mode."),
    Capability("system_capabilities", "system", "List the capabilities this ResearchMind instance exposes."),
    Capability("system_version", "system", "ResearchMind version and API surface information."),
]


def list_capabilities() -> list[dict]:
    """Safe discovery listing — no implementation details, no secrets (spec §35)."""
    return [
        {
            "name": c.name,
            "group": c.group,
            "description": c.description,
            "requires_network": c.requires_network,
            "may_invoke_llm": c.may_invoke_llm,
            "long_running": c.long_running,
            "mutating": c.mutating,
        }
        for c in REGISTRY
    ]
