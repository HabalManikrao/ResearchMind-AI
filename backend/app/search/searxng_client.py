"""SearXNG search client — a free, self-hosted, open-source alternative to Tavily.

SearXNG is a metasearch engine you run yourself (Docker); it fans a query out to
many upstream engines and returns merged results as JSON. Unlike Tavily it returns
*snippets*, not full page content, so this client optionally enriches the top
results by fetching each page through the SSRF-safe `net.safe_get` and extracting
readable text — falling back to the snippet if a fetch fails.

Requires the SearXNG instance to have JSON output enabled (settings.yml:
`search.formats: [html, json]`). The request to the SearXNG endpoint itself is not
routed through `validate_url` because the endpoint is operator-configured (and is
usually localhost); only the *result* URLs, which are web/model-derived, are.
"""
from __future__ import annotations

import asyncio
import html
import re

import httpx

from app.search.tavily_client import SearchError, SearchResult
from app.security import net

_UA = "ResearchMind/0.1 (+local research agent)"

# Strip <script>/<style> blocks, then all remaining tags.
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKLINES = re.compile(r"\n{3,}")


def _days_to_range(days: int) -> str:
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


def _html_to_text(raw: str, *, limit: int = 8000) -> str:
    """Very small readability pass: drop scripts/styles/tags, unescape, tidy."""
    text = _SCRIPT_STYLE.sub(" ", raw)
    text = _TAGS.sub(" ", text)
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _BLANKLINES.sub("\n\n", text)
    return text.strip()[:limit]


class SearxngClient:
    name = "searxng"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        fetch_content: bool = True,
        fetch_limit: int = 5,
        engines: str = "",
        verify_ssl: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.fetch_content = fetch_content
        self.fetch_limit = fetch_limit
        self.engines = [e.strip() for e in engines.split(",") if e.strip()]
        self.verify_ssl = verify_ssl

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        depth: str = "advanced",  # accepted for interface parity; unused
        topic: str | None = None,
        days: int | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        if not self.base_url:
            raise SearchError(
                "SEARXNG_URL is not set. Point it at a running SearXNG instance "
                "(e.g. http://localhost:8080) with JSON output enabled."
            )

        q = query
        if include_domains:
            # SearXNG has no include-domains param; use search operators instead.
            q = f"{query} (" + " OR ".join(f"site:{d}" for d in include_domains) + ")"

        params: dict = {"q": q, "format": "json"}
        if topic == "news":
            params["categories"] = "news"
        tr = time_range or (_days_to_range(days) if days else None)
        if tr:
            params["time_range"] = tr
        if self.engines:
            params["engines"] = ",".join(self.engines)

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, verify=self.verify_ssl, follow_redirects=True
            ) as client:
                resp = await client.get(
                    f"{self.base_url}/search", params=params,
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise SearchError(
                f"SearXNG returned {exc.response.status_code}. Ensure JSON output is "
                f"enabled in settings.yml (search.formats: [html, json])."
            ) from exc
        except httpx.HTTPError as exc:
            raise SearchError(
                f"SearXNG request failed ({exc}). Is the instance running at "
                f"{self.base_url}?"
            ) from exc
        except ValueError as exc:  # non-JSON body
            raise SearchError(
                "SearXNG did not return JSON. Enable JSON output in settings.yml "
                "(search.formats: [html, json])."
            ) from exc

        raw_results = data.get("results", [])[:max_results]
        # Normalize SearXNG scores (which can exceed 1 across engines) to 0-1 so
        # they match Tavily's contract and downstream scoring stays in range.
        max_score = max((float(r.get("score", 0.0)) for r in raw_results), default=0.0)

        results: list[SearchResult] = []
        for item in raw_results:
            url = item.get("url", "")
            if not url:
                continue
            raw_score = float(item.get("score", 0.0))
            score = round(raw_score / max_score, 4) if max_score > 0 else 0.5
            results.append(
                SearchResult(
                    title=item.get("title", "Untitled"),
                    url=url,
                    content=(item.get("content") or "").strip(),
                    score=score,
                    published_date=item.get("publishedDate"),
                )
            )

        if self.fetch_content:
            await self._enrich_content(results)
        # Drop any result we still have no usable text for.
        return [r for r in results if r.content]

    async def _enrich_content(self, results: list[SearchResult]) -> None:
        """Fetch the top results' pages and replace snippets with extracted text.
        SSRF-safe (via net.safe_get) and best-effort — failures keep the snippet."""
        targets = results[: self.fetch_limit]
        sem = asyncio.Semaphore(5)

        async with httpx.AsyncClient(
            timeout=min(self.timeout, 12.0), verify=self.verify_ssl,
            follow_redirects=True, headers={"User-Agent": _UA},
        ) as client:

            async def fetch(r: SearchResult) -> None:
                async with sem:
                    try:
                        resp = await net.safe_get(r.url, client=client)
                        resp.raise_for_status()
                        ctype = resp.headers.get("content-type", "")
                        if "html" not in ctype and "text" not in ctype:
                            return  # skip PDFs/binaries; keep snippet
                        text = _html_to_text(resp.text)
                        if len(text) > len(r.content):
                            r.content = text
                    except (httpx.HTTPError, net.UnsafeURLError, ValueError):
                        pass  # keep the snippet

            await asyncio.gather(*(fetch(r) for r in targets))
