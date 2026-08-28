"""GitHub Research Agent (spec Agent 5).

Searches GitHub repositories via the REST search API and analyses each repo's
metadata: language, license, stars/forks, activity (last push), open issues, and
whether it is active / archived. An LLM extracts relevance and practical findings
relative to the research question. Collection (API) stays separate from reasoning.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.agents.common import CollectedSource
from app.llm.base import AIProvider
from app.security.net import validate_url
from app.services.scoring import github_reliability

_SEARCH_URL = "https://api.github.com/search/repositories"

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
        "relevant": {"type": "boolean"},
    },
    "required": ["summary", "findings"],
}

_SYSTEM = (
    "You are analysing an open-source GitHub repository for a research question. "
    "Using only the provided metadata and description, summarise what the project "
    "does, its main features, and its practical advantages/limitations for the "
    "question. Do not invent features that are not indicated by the metadata."
)


def _is_active(pushed_at: str | None) -> bool:
    if not pushed_at:
        return False
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    # Active if pushed within ~18 months.
    return (datetime.now(timezone.utc) - dt).days < 550


async def _search_repos(query: str, token: str, max_results: int) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": max_results}
    validate_url(_SEARCH_URL)  # SSRF guard on outbound fetch (spec §21)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])


async def collect(
    provider: AIProvider,
    *,
    question: str,
    search_query: str,
    token: str = "",
    max_results: int = 5,
) -> list[CollectedSource]:
    items = await _search_repos(search_query, token, max_results)
    sources: list[CollectedSource] = []
    for repo in items:
        meta = {
            "owner": (repo.get("owner") or {}).get("login"),
            "language": repo.get("language"),
            "license": (repo.get("license") or {}).get("spdx_id"),
            "stars": repo.get("stargazers_count", 0),
            "forks": repo.get("forks_count", 0),
            "open_issues": repo.get("open_issues_count", 0),
            "last_push": repo.get("pushed_at"),
            "archived": bool(repo.get("archived", False)),
            "topics": repo.get("topics", []),
        }
        active = _is_active(meta["last_push"])
        meta["status"] = "archived" if meta["archived"] else ("active" if active else "inactive")

        content = (
            f"Repository: {repo.get('full_name')}\n"
            f"Description: {repo.get('description') or '—'}\n"
            f"Language: {meta['language']} | License: {meta['license']} | "
            f"Stars: {meta['stars']} | Forks: {meta['forks']} | "
            f"Open issues: {meta['open_issues']} | Status: {meta['status']}\n"
            f"Topics: {', '.join(meta['topics']) or '—'}"
        )
        summary, findings = await _analyse(provider, question, content)

        sources.append(
            CollectedSource(
                title=repo.get("full_name", "repo"),
                url=repo.get("html_url", ""),
                content=content,
                summary=summary,
                reliability_score=github_reliability(
                    meta["stars"], active=active, archived=meta["archived"]
                ),
                relevance_score=0.0,  # GitHub has no relevance score; ranked by stars
                source_type="github",
                published_date=meta["last_push"],
                findings=findings,
                meta=meta,
            )
        )
    return sources


async def _analyse(provider: AIProvider, question: str, content: str) -> tuple[str, list[str]]:
    prompt = (
        f"Research question:\n{question}\n\n{content}\n\n"
        "Analyse this repository's relevance and extract practical findings. Return JSON."
    )
    try:
        data = await provider.structured_output(
            prompt, schema=_ANALYSIS_SCHEMA, system=_SYSTEM
        )
    except Exception:
        return (content[:300], [])
    summary = str(data.get("summary", "")).strip()
    findings = [str(f).strip() for f in data.get("findings", []) if str(f).strip()]
    return summary, findings
