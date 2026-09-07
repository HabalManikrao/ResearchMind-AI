"""System capabilities (#8): safe, secret-free instance information (spec §16, §35).

Reuses the existing health/connectivity endpoints. Never returns filesystem paths, API
keys, tokens, or environment secrets."""
from __future__ import annotations

from app.api import system as sysapi
from app.capabilities.base import list_capabilities
from app.config import get_settings

API_VERSION = "1.0"


async def health(user=None) -> dict:
    return await sysapi.health()


async def connectivity(user=None) -> dict:
    return await sysapi.read_connectivity()


async def capabilities(user=None) -> dict:
    return {"capabilities": list_capabilities()}


async def version(user=None) -> dict:
    s = get_settings()
    return {
        "name": "ResearchMind AI",
        "api_version": API_VERSION,
        "interfaces": {"rest": "/v1", "mcp": True},
        "auth_enabled": s.auth_enabled,
        "capabilities": len(list_capabilities()),
    }
