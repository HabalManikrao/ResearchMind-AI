"""Extensible registries for knowledge-graph entity types and relationship predicates (#7).

These are validated **sets**, not enum columns (the DB stores plain strings), so adding a
type/predicate here needs no migration (spec §5, §7). Unknown values are coerced to a safe
default rather than rejected outright, so graph building never hard-fails on a novel label.
"""
from __future__ import annotations

# Entity types (spec §5). Extensible — add a member and nothing else changes.
ENTITY_TYPES = {
    "person",
    "organization",
    "company",
    "product",
    "technology",
    "software",
    "library",
    "framework",
    "location",
    "concept",
    "event",
    "project",
    "document",
    "other",
}
DEFAULT_ENTITY_TYPE = "other"

# Relationship predicates (spec §7). Bounded registry — not a free-text graph.
PREDICATES = {
    "related_to",
    "part_of",
    "depends_on",
    "built_by",
    "owned_by",
    "develops",
    "uses",
    "competes_with",
    "successor_of",
    "predecessor_of",
    "alternative_to",
    "integrates_with",
    "located_in",
    "member_of",
    "acquired_by",
    "acquired",
    "released_by",
}
DEFAULT_PREDICATE = "related_to"

# Claim↔claim predicates (spec §9).
CLAIM_PREDICATES = {
    "supersedes",
    "supports",
    "contradicts",
    "related_to",
    "depends_on",
}


def normalize_entity_type(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in ENTITY_TYPES else DEFAULT_ENTITY_TYPE


def normalize_predicate(value: str | None) -> str:
    v = (value or "").strip().lower()
    return v if v in PREDICATES else DEFAULT_PREDICATE


def is_valid_predicate(value: str | None) -> bool:
    return (value or "").strip().lower() in PREDICATES
