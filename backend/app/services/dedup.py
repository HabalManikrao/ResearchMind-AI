"""Duplicate detection (spec §2 "Remove duplicate information").

Runs as a pipeline stage once collection settles, when nothing else is writing:

- **Sources:** collapse entries that share a normalized URL, keeping the highest-
  reliability copy and re-pointing the duplicates' findings at it.
- **Findings:** drop near-duplicate finding texts (token Jaccard >= threshold),
  keeping the first occurrence.

Deliberately dependency-free (no embeddings) so it runs offline and fast; the
threshold approach can be upgraded to vector similarity when Qdrant lands.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import Finding, Source

_WORD = re.compile(r"[a-z0-9]+")


def normalize_url(url: str) -> str:
    p = urlparse(url.strip().lower())
    host = (p.hostname or "").removeprefix("www.")
    path = p.path.rstrip("/")
    return f"{host}{path}"  # ignore scheme, query, fragment, trailing slash


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def dedupe_project(project_id: str, *, finding_threshold: float = 0.85) -> dict:
    sources_removed = await _dedupe_sources(project_id)
    findings_removed = await _dedupe_findings(project_id, finding_threshold)
    return {"sources_removed": sources_removed, "findings_removed": findings_removed}


async def _dedupe_sources(project_id: str) -> int:
    async with SessionLocal() as db:
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()

        groups: dict[str, list[Source]] = {}
        for s in sources:
            groups.setdefault(normalize_url(s.url), []).append(s)

        removed = 0
        for grp in groups.values():
            if len(grp) < 2:
                continue
            grp.sort(key=lambda x: x.reliability_score, reverse=True)
            keep, dups = grp[0], grp[1:]
            for dup in dups:
                await db.execute(
                    update(Finding)
                    .where(Finding.source_id == dup.id)
                    .values(source_id=keep.id)
                )
                await db.delete(dup)
                removed += 1
        await db.commit()
        return removed


async def _dedupe_findings(project_id: str, threshold: float) -> int:
    async with SessionLocal() as db:
        findings = (
            await db.execute(
                select(Finding)
                .where(Finding.project_id == project_id)
                .order_by(Finding.created_at)
            )
        ).scalars().all()

        kept_tokens: list[set[str]] = []
        removed = 0
        for f in findings:
            toks = _tokens(f.text)
            if any(_jaccard(toks, kt) >= threshold for kt in kept_tokens):
                await db.delete(f)
                removed += 1
            else:
                kept_tokens.append(toks)
        await db.commit()
        return removed
