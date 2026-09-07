"""ResearchMind Capability Layer (#8).

The single, transport-agnostic implementation of each ResearchMind capability. REST (`/v1`)
and MCP are thin adapters over these functions — there is exactly one implementation of each
capability, and it reuses the existing services (research engine, diff, knowledge graph,
monitoring, connectivity, documents) and ownership helpers. No capability contains a second
research/evidence/diff/graph engine (spec §1, §4, §55).
"""
from app.capabilities.base import (
    CapabilityError,
    REGISTRY,
    codes,
    list_capabilities,
    resolve_user,
)

__all__ = [
    "CapabilityError",
    "REGISTRY",
    "codes",
    "list_capabilities",
    "resolve_user",
]
