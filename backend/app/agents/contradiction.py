"""Active Contradiction Search (spec §6, §23.3).

Verification (`verification.py`) reasons over evidence already collected — it can
only surface disagreement that happens to be in hand. This agent goes further: for
the most important claims it *actively searches the web for disconfirming
evidence*, so a claim isn't marked confident just because nobody looked for the
counter-argument ("never trust a single source").

It is deliberately bounded — one search + one extraction call per claim, and the
orchestrator only feeds it the top-N high-confidence claims — because runs are
CPU-only. Every step is fail-safe: a search or extraction error skips that claim
rather than breaking the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import AIProvider
from app.search import SearchError
from app.services.scoring import reliability_score

_SCHEMA = {
    "type": "object",
    "properties": {
        "contradictions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "quote": {"type": "string"},
                },
                "required": ["index", "quote"],
            },
        }
    },
    "required": ["contradictions"],
}

_SYSTEM = (
    "You check whether sources provide evidence that CONTRADICTS a specific claim. "
    "Include a source only if it genuinely disputes, refutes, or presents facts "
    "incompatible with the claim — ignore sources that merely discuss, qualify, or "
    "support it. For each contradicting source, quote the specific sentence that "
    "does the contradicting. Return an empty list if none contradict."
)


@dataclass
class ContradictingSource:
    title: str
    url: str
    content: str
    passage: str  # the quoted contradicting sentence
    reliability: float
    published_date: str | None = None
    source_type: str = "web"


@dataclass
class ClaimContradiction:
    claim_id: str
    sources: list[ContradictingSource] = field(default_factory=list)


def _refutation_query(claim_text: str) -> str:
    # A disconfirming-biased query. No LLM call here (keeps CPU cost to one call
    # per claim, in the extraction step).
    trimmed = claim_text.strip().rstrip(".")[:180]
    return f"{trimmed} criticism OR limitations OR counterevidence OR debunked OR inaccurate"


async def seek(
    provider: AIProvider,
    search_client,
    claims: list[tuple[str, str]],
    *,
    max_results: int = 4,
) -> list[ClaimContradiction]:
    """`claims` is a list of (claim_id, claim_text). Returns, per claim, any
    sources found that genuinely contradict it."""
    out: list[ClaimContradiction] = []
    for claim_id, text in claims:
        try:
            found = await _seek_one(provider, search_client, text, max_results)
        except Exception:  # noqa: BLE001 - never let one claim break the batch
            found = []
        if found:
            out.append(ClaimContradiction(claim_id=claim_id, sources=found))
    return out


async def _seek_one(
    provider: AIProvider, search_client, claim_text: str, max_results: int
) -> list[ContradictingSource]:
    try:
        results = await search_client.search(
            _refutation_query(claim_text), max_results=max_results
        )
    except SearchError:
        return []
    results = [r for r in results if getattr(r, "url", "") and getattr(r, "content", "")]
    if not results:
        return []

    listing = "\n\n".join(
        f"[{i}] {r.title} ({r.url})\n{r.content[:1500]}"
        for i, r in enumerate(results)
    )
    prompt = (
        f"Claim:\n{claim_text}\n\n"
        f"Candidate sources:\n{listing}\n\n"
        "Which sources contradict the claim? Quote the contradicting sentence. "
        "Return JSON."
    )
    try:
        data = await provider.structured_output(prompt, schema=_SCHEMA, system=_SYSTEM)
    except Exception:  # noqa: BLE001
        return []

    contradicting: list[ContradictingSource] = []
    seen: set[str] = set()
    for c in data.get("contradictions", []):
        idx = c.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(results)):
            continue
        r = results[idx]
        if r.url in seen:
            continue
        seen.add(r.url)
        quote = str(c.get("quote", "")).strip()
        contradicting.append(
            ContradictingSource(
                title=r.title,
                url=r.url,
                content=r.content,
                passage=quote,
                reliability=reliability_score(r.url, relevance=getattr(r, "score", 0.0)),
                published_date=getattr(r, "published_date", None),
                source_type="web",
            )
        )
    return contradicting
