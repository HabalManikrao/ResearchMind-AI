"""ResearchMind external REST API v1 (#8) — a thin adapter over the capability layer.

Every endpoint calls a capability function (the single implementation) and returns its
plain-dict result. Ownership/auth reuse the existing JWT dependency; errors surface through
the structured envelope (registered in ``main.py``); request IDs come from the middleware.
Existing internal routes are untouched — this is an additive, versioned external contract.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from app.capabilities import documents as cap_docs
from app.capabilities import knowledge as cap_kg
from app.capabilities import monitoring as cap_mon
from app.capabilities import research as cap_research
from app.capabilities import system as cap_system
from app.models import User
from app.security.auth import get_current_user

router = APIRouter(prefix="/v1", tags=["v1"])


def _idem(request: Request) -> str | None:
    return request.headers.get("Idempotency-Key") or None


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# --------------------------------------------------------------------------- #
# Request bodies (documented in OpenAPI)
# --------------------------------------------------------------------------- #
class StartResearchBody(BaseModel):
    query: str = Field(min_length=3, description="The research question.")
    sources_enabled: list[str] | None = Field(None, description="Source agents, e.g. ['web','papers'].")
    mode: str = Field("deep", description="quick|standard|deep|technical_rd|comparison|decision|market")
    source_policy: str | None = Field(None, description="live_only|live_preferred|cache_allowed|local_only")
    constraints: dict | None = None


class AgainBody(BaseModel):
    intent: str = Field("refresh", description="refresh|deepen|verify|full")
    sources_enabled: list[str] | None = None


class DocSearchBody(BaseModel):
    project_id: str
    query: str = Field(min_length=1)
    top_k: int | None = Field(None, ge=1)


# --------------------------------------------------------------------------- #
# Research
# --------------------------------------------------------------------------- #
@router.get("/research", summary="Search prior research")
async def v1_research_search(
    q: str | None = Query(None), limit: int | None = Query(None), offset: int = Query(0),
    user: User = Depends(get_current_user),
):
    return await cap_research.search(user, q=q, limit=limit, offset=offset)


@router.post("/research", status_code=202, summary="Start research (returns immediately)")
async def v1_research_start(
    request: Request, response: Response, body: StartResearchBody = Body(...),
    user: User = Depends(get_current_user),
):
    result = await cap_research.start(
        user, query=body.query, sources_enabled=body.sources_enabled, mode=body.mode,
        source_policy=body.source_policy, constraints=body.constraints,
        idempotency_key=_idem(request), client_ip=_client_ip(request),
    )
    response.headers["Location"] = f"/v1/research/{result['research_id']}/status"
    return result


@router.get("/research/{research_id}/status", summary="Research status")
async def v1_research_status(research_id: str, user: User = Depends(get_current_user)):
    return await cap_research.status(user, research_id)


@router.get("/research/{research_id}/report", summary="Research report")
async def v1_research_report(
    research_id: str, excerpt: bool = Query(False), user: User = Depends(get_current_user),
):
    return await cap_research.report(user, research_id, excerpt=excerpt)


@router.get("/research/{research_id}/claims", summary="Research claims")
async def v1_research_claims(
    research_id: str, limit: int | None = Query(None), offset: int = Query(0),
    user: User = Depends(get_current_user),
):
    return await cap_research.claims(user, research_id, limit=limit, offset=offset)


@router.get("/research/{research_id}/claims/{claim_id}/evidence", summary="Claim evidence")
async def v1_research_evidence(
    research_id: str, claim_id: str, user: User = Depends(get_current_user),
):
    return await cap_research.evidence(user, research_id, claim_id)


@router.post("/research/{research_id}/again", status_code=202, summary="Continue research")
async def v1_research_again(
    research_id: str, request: Request, body: AgainBody = Body(...),
    user: User = Depends(get_current_user),
):
    return await cap_research.again(
        user, research_id, intent=body.intent, sources_enabled=body.sources_enabled,
        idempotency_key=_idem(request), client_ip=_client_ip(request),
    )


@router.get("/research/{research_id}/diff/{other_id}", summary="Diff two runs")
async def v1_research_diff(
    research_id: str, other_id: str, user: User = Depends(get_current_user),
):
    return await cap_research.diff(user, research_id, other_id)


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
@router.get("/documents", summary="List a project's documents")
async def v1_documents_list(project_id: str = Query(...), user: User = Depends(get_current_user)):
    return await cap_docs.documents_list(user, project_id)


@router.post("/documents/search", summary="Semantic search over documents")
async def v1_documents_search(
    body: DocSearchBody = Body(...), user: User = Depends(get_current_user),
):
    return await cap_docs.search(user, body.project_id, body.query, top_k=body.top_k)


# --------------------------------------------------------------------------- #
# Knowledge graph
# --------------------------------------------------------------------------- #
@router.get("/knowledge/entities", summary="Search entities")
async def v1_entities(
    q: str | None = Query(None), type: str | None = Query(None),
    limit: int | None = Query(None), offset: int = Query(0),
    user: User = Depends(get_current_user),
):
    return await cap_kg.entity_search(user, q=q, type=type, limit=limit, offset=offset)


@router.get("/knowledge/entities/{entity_id}", summary="Entity detail")
async def v1_entity(entity_id: str, user: User = Depends(get_current_user)):
    return await cap_kg.entity(user, entity_id)


@router.get("/knowledge/entities/{entity_id}/graph", summary="Entity neighbourhood (bounded)")
async def v1_entity_graph(
    entity_id: str, depth: int = Query(1, ge=1), user: User = Depends(get_current_user),
):
    return await cap_kg.graph(user, entity_id, depth=depth)


@router.get("/knowledge/entities/{entity_id}/claims", summary="Entity claims")
async def v1_entity_claims(
    entity_id: str, scope: str = Query("all"), user: User = Depends(get_current_user),
):
    return await cap_kg.entity_claims(user, entity_id, scope=scope)


@router.get("/knowledge/entities/{entity_id}/history", summary="Entity history")
async def v1_entity_history(entity_id: str, user: User = Depends(get_current_user)):
    return await cap_kg.entity_history(user, entity_id)


# --------------------------------------------------------------------------- #
# Monitoring (read-only)
# --------------------------------------------------------------------------- #
@router.get("/monitors/{project_id}", summary="Monitor status")
async def v1_monitor_status(project_id: str, user: User = Depends(get_current_user)):
    return await cap_mon.status(user, project_id)


@router.get("/monitors/{project_id}/history", summary="Monitor change history")
async def v1_monitor_history(project_id: str, user: User = Depends(get_current_user)):
    return await cap_mon.changes(user, project_id)


# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
@router.get("/system/connectivity", summary="Connectivity + research mode")
async def v1_connectivity(user: User = Depends(get_current_user)):
    return await cap_system.connectivity(user)


@router.get("/system/capabilities", summary="List capabilities")
async def v1_capabilities(user: User = Depends(get_current_user)):
    return await cap_system.capabilities(user)


@router.get("/system/version", summary="Version + interfaces")
async def v1_version(user: User = Depends(get_current_user)):
    return await cap_system.version(user)
