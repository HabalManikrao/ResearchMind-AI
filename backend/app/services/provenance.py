"""Source provenance & availability (Connectivity Intelligence, #5).

Two distinct concepts (spec §3, §7, §8):

- **Provenance** — *where* a persisted piece of evidence actually came from. Stamped
  onto ``Source.meta["provenance"]`` at collection time and never inferred after the
  fact. A source is ``LIVE_WEB`` **only** when an external provider returned it during
  the current run; a cache reuse is ``CACHED_WEB``; local retrieval is ``LOCAL_*``.

- **Availability** — the *display state* derived from provenance + freshness, shown as
  a badge so a reader can see at a glance whether evidence is live, cached, local or
  stale. This is derived, not stored, so it always reflects current freshness.

``UNAVAILABLE`` is deliberately **not** a persisted-source state: a persisted ``Source``
is evidence we actually hold. A source that could not be fetched has no row; it is
counted at the run-health level instead (so we never invent phantom "unavailable"
sources — spec §34).
"""
from __future__ import annotations

# --- Provenance: where the evidence came from ------------------------------ #
LIVE_WEB = "live_web"
CACHED_WEB = "cached_web"
LOCAL_DOCUMENT = "local_document"
LOCAL_MEMORY = "local_memory"
LOCAL_DATABASE = "local_database"

# --- Availability: display state (spec §3) --------------------------------- #
LIVE = "live"
CACHED = "cached"
LOCAL = "local"
STALE = "stale"
UNAVAILABLE = "unavailable"
UNKNOWN = "unknown"

# External source types are fetched over the network; the rest are local.
EXTERNAL_SOURCE_TYPES = frozenset({"web", "docs", "news", "community", "github", "papers"})
LOCAL_SOURCE_TYPES = frozenset({"documents"})

# Default provenance for a source type when nothing more specific was stamped.
_DEFAULT_PROVENANCE = {
    "documents": LOCAL_DOCUMENT,
}


def is_external(source_type: str) -> bool:
    """True for source types that require a network fetch (web/docs/news/community/
    github/papers). Local types (documents) are False."""
    return source_type in EXTERNAL_SOURCE_TYPES


def default_provenance(source_type: str) -> str:
    """The provenance to assume for a source type absent an explicit stamp. Local
    types are local; external types are treated as live (they only exist as rows
    because a live fetch produced them)."""
    return _DEFAULT_PROVENANCE.get(source_type, LIVE_WEB if is_external(source_type) else LOCAL_DATABASE)


def provenance_of(source_type: str, meta: dict | None) -> str:
    """Read the stamped provenance from a source's meta, falling back to the type
    default. Never guesses "live" for something that wasn't actually fetched live —
    the default for external types reflects that an external row *is* a live result
    unless explicitly stamped ``cached_web``."""
    prov = (meta or {}).get("provenance")
    if prov in (LIVE_WEB, CACHED_WEB, LOCAL_DOCUMENT, LOCAL_MEMORY, LOCAL_DATABASE):
        return prov
    return default_provenance(source_type)


def availability_of(provenance: str, freshness: str) -> str:
    """Derive the display availability from provenance + freshness (spec §3).

    Freshness wins when evidence exists but is stale; otherwise provenance maps
    straight through. This keeps "cached recently" distinct from "live" and
    "uploaded today" distinct from "published today".
    """
    if freshness == "stale":
        return STALE
    if provenance == CACHED_WEB:
        return CACHED
    if provenance in (LOCAL_DOCUMENT, LOCAL_MEMORY, LOCAL_DATABASE):
        return LOCAL
    if provenance == LIVE_WEB:
        return LIVE
    return UNKNOWN


# Research-health labels for a whole run (spec §22).
FULLY_LIVE = "fully_live"
PARTIALLY_DEGRADED = "partially_degraded"
CACHE_ASSISTED = "cache_assisted"
LOCAL_ONLY = "local_only"
EXTERNAL_UNAVAILABLE = "external_unavailable"


def research_health(
    *, live: int, cached: int, local: int, unavailable: int
) -> str:
    """Summarise a run's overall source health into one label (spec §22).

    Honest by construction: ``fully_live`` only when nothing was cached, local-only or
    unavailable; ``external_unavailable`` only when external evidence was requested but
    none (live or cached) came back.
    """
    if unavailable and not live and not cached and not local:
        return EXTERNAL_UNAVAILABLE
    if live and not cached and not unavailable and not local:
        return FULLY_LIVE
    if not live and not cached and local:
        return LOCAL_ONLY
    if cached and not live:
        return CACHE_ASSISTED
    if unavailable or cached:
        return PARTIALLY_DEGRADED
    if live:
        return FULLY_LIVE
    return LOCAL_ONLY
