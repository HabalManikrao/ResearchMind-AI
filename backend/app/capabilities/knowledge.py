"""Knowledge-graph capabilities (#8): entity search/detail/graph/claims/history.

Delegates to the **single** #7 implementation in ``api.graph`` (ownership-scoped, depth-
clamped, paginated) so REST/MCP and the internal UI share exactly one graph read path
(spec §14, §55). HTTPExceptions from that layer are mapped to the capability error contract.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.api import graph as gapi
from app.capabilities.base import clamp_page, map_http_error
from app.database import SessionLocal


def _dump(model) -> dict:
    return model.model_dump()


async def entity_search(user, *, q: str | None = None, type: str | None = None,
                        limit: int | None = None, offset: int | None = None) -> dict:
    lim, off = clamp_page(limit, offset)
    async with SessionLocal() as db:
        try:
            rows = await gapi.list_entities(q=q, type=type, limit=lim, offset=off, db=db, user=user)
        except HTTPException as e:
            raise map_http_error(e)
    return {"limit": lim, "offset": off, "entities": [_dump(r) for r in rows]}


async def entity(user, entity_id: str) -> dict:
    async with SessionLocal() as db:
        try:
            return _dump(await gapi.get_entity(entity_id, db=db, user=user))
        except HTTPException as e:
            raise map_http_error(e)


async def graph(user, entity_id: str, *, depth: int = 1) -> dict:
    async with SessionLocal() as db:
        try:
            return _dump(await gapi.get_entity_graph(entity_id, depth=depth, db=db, user=user))
        except HTTPException as e:
            raise map_http_error(e)


async def entity_claims(user, entity_id: str, *, scope: str = "all") -> dict:
    if scope not in ("current", "historical", "all"):
        from app.capabilities.base import CapabilityError, codes

        raise CapabilityError(codes.INVALID_ARGUMENT, "scope must be current|historical|all")
    async with SessionLocal() as db:
        try:
            rows = await gapi.get_entity_claims(entity_id, scope=scope, db=db, user=user)
        except HTTPException as e:
            raise map_http_error(e)
    return {"entity_id": entity_id, "scope": scope, "claims": [_dump(r) for r in rows]}


async def entity_history(user, entity_id: str) -> dict:
    async with SessionLocal() as db:
        try:
            return _dump(await gapi.get_entity_history(entity_id, db=db, user=user))
        except HTTPException as e:
            raise map_http_error(e)
