"""Academic Research Agent (spec Agent 6).

Queries the arXiv API and analyses each paper's practical relevance — not just its
title. Extracts the research problem, methodology, results, and limitations relative
to the research question (spec: "Analyze the practical relevance of each paper").
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.agents.common import CollectedSource
from app.llm.base import AIProvider
from app.security.net import validate_url
from app.services.scoring import academic_reliability

_ARXIV_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "methodology": {"type": "string"},
        "limitations": {"type": "string"},
    },
    "required": ["summary", "findings"],
}

_SYSTEM = (
    "You analyse an academic paper's abstract for a research question. Summarise the "
    "research problem, methodology, results, and limitations, and extract findings "
    "that are practically relevant to the question. Use only the abstract provided."
)


async def _search_arxiv(query: str, max_results: int) -> list[dict]:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    validate_url(_ARXIV_URL)  # SSRF guard on outbound fetch (spec §21)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(_ARXIV_URL, params=params)
        resp.raise_for_status()
        text = resp.text

    root = ET.fromstring(text)
    papers: list[dict] = []
    for entry in root.findall(f"{_ATOM}entry"):
        title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
        summary = (entry.findtext(f"{_ATOM}summary") or "").strip().replace("\n", " ")
        published = (entry.findtext(f"{_ATOM}published") or "")[:10]
        authors = [
            (a.findtext(f"{_ATOM}name") or "").strip()
            for a in entry.findall(f"{_ATOM}author")
        ]
        link = ""
        for lnk in entry.findall(f"{_ATOM}link"):
            if lnk.get("rel") == "alternate":
                link = lnk.get("href", "")
        papers.append(
            {
                "title": title,
                "abstract": summary,
                "published": published,
                "authors": authors,
                "url": link,
            }
        )
    return papers


async def collect(
    provider: AIProvider,
    *,
    question: str,
    search_query: str,
    max_results: int = 5,
) -> list[CollectedSource]:
    papers = await _search_arxiv(search_query, max_results)
    sources: list[CollectedSource] = []
    for p in papers:
        if not p["url"] or not p["abstract"]:
            continue
        analysis = await _analyse(provider, question, p)
        meta = {
            "authors": p["authors"],
            "methodology": analysis.get("methodology"),
            "limitations": analysis.get("limitations"),
            "venue": "arXiv",
        }
        sources.append(
            CollectedSource(
                title=p["title"],
                url=p["url"],
                content=p["abstract"],
                summary=str(analysis.get("summary", "")).strip(),
                reliability_score=academic_reliability(),
                relevance_score=0.0,
                source_type="papers",
                published_date=p["published"],
                findings=[
                    str(f).strip()
                    for f in analysis.get("findings", [])
                    if str(f).strip()
                ],
                meta=meta,
            )
        )
    return sources


async def _analyse(provider: AIProvider, question: str, paper: dict) -> dict:
    prompt = (
        f"Research question:\n{question}\n\n"
        f"Paper: {paper['title']}\n"
        f"Authors: {', '.join(paper['authors'][:8])}\n"
        f"Abstract:\n{paper['abstract'][:6000]}\n\n"
        "Analyse practical relevance and extract findings. Return JSON."
    )
    try:
        return await provider.structured_output(
            prompt, schema=_ANALYSIS_SCHEMA, system=_SYSTEM
        )
    except Exception:
        return {"summary": paper["abstract"][:300], "findings": []}
