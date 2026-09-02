"""Significance engine (#6, spec §8, §10, §18): decide whether a detected change matters.

This is the core of research monitoring. It takes the **existing** deterministic
``ResearchDiff`` (``services/research_diff.diff_runs``) — so there is no second diff
system (spec §24) — and classifies each change with an **impact** level. It is fully
deterministic and transparent: every ``Change`` carries reasons built from the diff's own
evidence-derived fields, never invented and never an opaque LLM score (spec §10).

The product rule it encodes: *a new source alone is not important; a change to what the
user should believe is.* So 10 new low-quality sources produce only LOW noise (suppressed),
while one authoritative source that contradicts a major claim is CRITICAL (spec §18).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.config import Settings
from app.services import research_diff as rd
from app.services.dedup import normalize_url

# Impact levels, low → high.
LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"
_RANK = {LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}

# Notification policy → the minimum impact that triggers a notification (spec §14).
_POLICY_THRESHOLD = {"all": MEDIUM, "important": HIGH, "critical": CRITICAL}

# Source types treated as authoritative/primary for the significance gate (spec §18).
AUTHORITATIVE_TYPES = {"papers", "docs", "github"}

_WORD = re.compile(r"[a-z0-9]+")


def _norm(text: str | None) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _bucket(conf: float | None) -> str:
    """Coarse confidence bucket so re-detecting the same change at the same confidence
    dedupes, but a *further* move produces a new alert (spec §17)."""
    if conf is None:
        return "na"
    return str(int(round(conf / 10.0)))


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass
class Change:
    kind: str          # claim_contradicted|claim_weakened|claim_strengthened|claim_new|
                       # claim_removed|recommendation_reversed|recommendation_modified|
                       # recommendation_new|recommendation_removed|source_unavailable|source_new
    impact: str        # low|medium|high|critical
    title: str
    detail: str
    dedup_key: str
    reasons: list[str] = field(default_factory=list)
    refs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "impact": self.impact,
            "title": self.title,
            "detail": self.detail,
            "dedup_key": self.dedup_key,
            "reasons": self.reasons,
            "refs": self.refs,
        }


def rank(impact: str) -> int:
    return _RANK.get(impact, 0)


def max_impact(changes: list[Change]) -> str | None:
    return max((c.impact for c in changes), key=rank, default=None)


def notify_threshold(notify_policy: str) -> str:
    return _POLICY_THRESHOLD.get(notify_policy, MEDIUM)


def is_meaningful(change: Change) -> bool:
    """LOW is noise; MEDIUM+ is a meaningful change to knowledge (spec §11, §18)."""
    return rank(change.impact) >= rank(MEDIUM)


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate(
    diff: rd.ResearchDiff,
    settings: Settings,
    *,
    source_reliability: dict | None = None,
) -> list[Change]:
    """Classify every change in ``diff``. ``source_reliability`` maps a normalized new-run
    URL → (reliability, source_type) so a brand-new authoritative source can be rated;
    optional (bare new sources default to LOW noise without it)."""
    changes: list[Change] = []
    changes.extend(_recommendation_changes(diff.recommendation))
    changes.extend(_claim_changes(diff.claims, settings))
    changes.extend(_source_changes(diff.sources, settings, source_reliability or {}))
    # Highest-impact first for display; stable within a level by insertion order.
    changes.sort(key=lambda c: -rank(c.impact))
    return changes


def _recommendation_changes(recommendation: dict) -> list[Change]:
    kind = recommendation.get("kind")
    old = (recommendation.get("old") or {}).get("option") if recommendation.get("old") else None
    new = (recommendation.get("new") or {}).get("option") if recommendation.get("new") else None
    if kind == "reversed":
        return [Change(
            kind="recommendation_reversed", impact=CRITICAL,
            title="Recommendation changed",
            detail=f"Recommendation changed from “{old}” to “{new}”.",
            dedup_key=_key("recommendation", "reversed", _norm(new)),
            reasons=["the recommended option is different"],
            refs={"old": old, "new": new},
        )]
    if kind == "modified":
        return [Change(
            kind="recommendation_modified", impact=HIGH,
            title="Recommendation updated",
            detail=f"The rationale or confidence behind “{new}” changed.",
            dedup_key=_key("recommendation", "modified", _norm(new)),
            reasons=["recommendation rationale/confidence changed"],
            refs={"old": old, "new": new},
        )]
    if kind == "removed":
        return [Change(
            kind="recommendation_removed", impact=HIGH,
            title="Recommendation withdrawn",
            detail=f"The prior recommendation “{old}” is no longer supported.",
            dedup_key=_key("recommendation", "removed", _norm(old)),
            reasons=["no recommendation in the new run"],
            refs={"old": old, "new": None},
        )]
    if kind == "new":
        return [Change(
            kind="recommendation_new", impact=MEDIUM,
            title="New recommendation",
            detail=f"A recommendation emerged: “{new}”.",
            dedup_key=_key("recommendation", "new", _norm(new)),
            reasons=["a recommendation now exists"],
            refs={"old": None, "new": new},
        )]
    return []


def _claim_changes(claims: dict, settings: Settings) -> list[Change]:
    out: list[Change] = []
    for it in claims.get("items", []):
        # ClaimDiffItem dataclass or dict — support both.
        kind = _get(it, "kind")
        old_text = _get(it, "old_text")
        new_text = _get(it, "new_text")
        old_c = _get(it, "old_confidence")
        new_c = _get(it, "new_confidence")
        delta = _get(it, "confidence_delta")
        reason = _get(it, "reason") or ""
        new_ev = _get(it, "new_evidence") or []
        text = new_text or old_text or ""

        reasons = [reason] if reason else []

        if kind == rd.CONTRADICTED:
            important = (old_c or 0) >= settings.monitor_high_confidence
            impact = CRITICAL if important else HIGH
            out.append(Change(
                kind="claim_contradicted", impact=impact,
                title="A supported claim is now contradicted",
                detail=f"“{_short(text)}” — {reason or 'new contradicting evidence discovered'}.",
                dedup_key=_key("claim", "contradicted", _norm(text), _bucket(new_c)),
                reasons=reasons or ["new contradicting evidence discovered"],
                refs=_claim_refs(text, old_c, new_c, new_ev),
            ))
        elif kind == rd.WEAKENED:
            mag = abs(delta) if delta is not None else 0.0
            impact = HIGH if mag >= settings.monitor_major_delta else MEDIUM
            out.append(Change(
                kind="claim_weakened", impact=impact,
                title="A claim's confidence dropped",
                detail=f"“{_short(text)}” — confidence {_round(old_c)} → {_round(new_c)}.",
                dedup_key=_key("claim", "weakened", _norm(text), _bucket(new_c)),
                reasons=reasons or ["confidence decreased"],
                refs=_claim_refs(text, old_c, new_c, new_ev),
            ))
        elif kind == rd.STRENGTHENED:
            mag = abs(delta) if delta is not None else 0.0
            impact = MEDIUM if mag >= settings.monitor_major_delta else LOW
            out.append(Change(
                kind="claim_strengthened", impact=impact,
                title="A claim was strengthened",
                detail=f"“{_short(text)}” — confidence {_round(old_c)} → {_round(new_c)}.",
                dedup_key=_key("claim", "strengthened", _norm(text), _bucket(new_c)),
                reasons=reasons or ["confidence increased"],
                refs=_claim_refs(text, old_c, new_c, new_ev),
            ))
        elif kind == rd.NEW:
            supports = sum(1 for e in new_ev if _get(e, "stance") == "supports")
            authoritative = any(
                _get(e, "source_type") in AUTHORITATIVE_TYPES for e in new_ev
            )
            impact = MEDIUM if (supports >= 2 or authoritative) else LOW
            out.append(Change(
                kind="claim_new", impact=impact,
                title="New claim discovered",
                detail=f"“{_short(text)}” ({supports} supporting source(s)).",
                dedup_key=_key("claim", "new", _norm(text)),
                reasons=reasons or ["new claim"],
                refs=_claim_refs(text, old_c, new_c, new_ev),
            ))
        elif kind == rd.REMOVED:
            impact = MEDIUM if (old_c or 0) >= settings.monitor_high_confidence else LOW
            out.append(Change(
                kind="claim_removed", impact=impact,
                title="A claim is no longer present",
                detail=f"“{_short(text)}” was in the previous research but not the latest.",
                dedup_key=_key("claim", "removed", _norm(text)),
                reasons=reasons or ["claim no longer present"],
                refs=_claim_refs(text, old_c, new_c, []),
            ))
        # UNCHANGED → not a change.
    return out


def _source_changes(sources: dict, settings: Settings, reliability: dict) -> list[Change]:
    out: list[Change] = []
    for it in sources.get("items", []):
        kind = _get(it, "kind")
        url = _get(it, "url")
        title = _get(it, "title") or url
        stype = _get(it, "source_type")
        changes_list = _get(it, "changes") or []

        if kind == rd.CHANGED:
            became_unavailable = any(
                "→ unavailable" in c or "unavailable" == c.split(" ")[-1]
                for c in changes_list
                if "availability" in c
            )
            if became_unavailable:
                out.append(Change(
                    kind="source_unavailable", impact=MEDIUM,
                    title="A cited source became unavailable",
                    detail=f"“{_short(title)}” is no longer reachable.",
                    dedup_key=_key("source", "unavailable", normalize_url(url or "")),
                    reasons=[c for c in changes_list if "availability" in c],
                    refs={"url": url},
                ))
            # Other source changes (freshness, live→cached provenance) are disclosure,
            # not a knowledge change — not surfaced as an alert (spec §16, §19).
        elif kind == rd.NEW:
            rel, rtype = reliability.get(normalize_url(url or ""), (None, stype))
            authoritative = (
                (rel is not None and rel >= settings.monitor_authoritative_reliability)
                or (rtype in AUTHORITATIVE_TYPES)
            )
            # A bare new source is LOW noise; only a genuinely authoritative/primary new
            # source rises to MEDIUM (spec §8 "important new primary source", §18).
            impact = MEDIUM if authoritative else LOW
            out.append(Change(
                kind="source_new", impact=impact,
                title="New source found",
                detail=f"“{_short(title)}”"
                       + (f" (reliability {_round(rel)})" if rel is not None else ""),
                dedup_key=_key("source", "new", normalize_url(url or "")),
                reasons=["authoritative/primary source" if authoritative else "new source"],
                refs={"url": url, "reliability": rel},
            ))
        # REMOVED/UNCHANGED sources are not knowledge changes on their own.
    return out


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _get(obj, name):
    """Read a field from a dataclass item or a plain dict (diff items are dataclasses)."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _short(text: str, n: int = 140) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _round(v):
    return round(v) if isinstance(v, (int, float)) else "?"


def _claim_refs(text, old_c, new_c, evidence) -> dict:
    return {
        "claim_text": _short(text, 240),
        "old_confidence": old_c,
        "new_confidence": new_c,
        "evidence_count": len(evidence or []),
    }
