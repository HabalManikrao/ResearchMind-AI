"""Shared test configuration and fixtures.

Environment is set BEFORE any app import so the module-level DB engine and cached
settings bind to an isolated temp SQLite database and Qdrant path. Each test runs
against a freshly recreated schema for full isolation.
"""
from __future__ import annotations

import hashlib
import math
import os
import tempfile

# --- Isolated environment (must precede app imports) ----------------------- #
_TMP = tempfile.mkdtemp(prefix="rmtest_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["QDRANT_PATH"] = f"{_TMP}/qdrant"
os.environ["DOCUMENT_STORAGE_DIR"] = f"{_TMP}/documents"
os.environ["KNOWLEDGE_ENABLED"] = "true"
os.environ["TAVILY_API_KEY"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"  # disabled globally; tested in isolation
os.environ["AUTH_ENABLED"] = "true"  # exercise real auth in the suite
os.environ["JWT_SECRET"] = "test-secret-key"
os.environ["SCHEDULER_ENABLED"] = "false"  # drive scheduler explicitly in tests
# Pin research budgets so the suite is hermetic — otherwise a developer's tuned
# backend/.env (e.g. MAX_RESEARCH_TASKS=3 for slow CPU boxes) leaks in and starves
# multi-source dispatch tests. These match the code defaults the tests target.
os.environ["MAX_RESEARCH_TASKS"] = "24"
os.environ["MAX_FOLLOWUP_ROUNDS"] = "2"
os.environ["MAX_SOURCES_PER_TASK"] = "5"
# Fake test embeddings (bag-of-words hashing) give low cosine scores; drop the
# document retrieval floor so retrieval is deterministic in the suite. Production
# keeps the real default (0.25).
os.environ["DOCUMENT_RETRIEVAL_MIN_SCORE"] = "0"

import httpx  # noqa: E402
import pytest  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
def _fake_vec(text: str, dim: int = 32) -> list[float]:
    v = [0.0] * dim
    for w in text.lower().split():
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class FakeProvider:
    """A deterministic provider that branches structured_output by schema shape,
    so it stands in for a real LLM across every agent."""

    name = "fake"

    def __init__(self, *, claims=None, conflicts=None, gaps=None, contradictions=None):
        self._claims = claims
        self._conflicts = conflicts
        self._gaps = gaps
        self._contradictions = contradictions

    async def generate(self, prompt, system=None):
        return (
            "## Executive Summary\nSummary text.\n"
            "## Key Findings\n- A finding\n"
            "## Detailed Analysis\nAnalysis.\n## Knowledge Gaps\nNone."
        )

    async def structured_output(self, prompt, schema, system=None):
        props = schema.get("properties", {})
        if "objective" in props:
            return {
                "objective": "Test objective",
                "questions": [
                    {"text": "Q1?", "priority": 1, "search_query": "q1"},
                    {"text": "Q2?", "priority": 2, "search_query": "q2"},
                ],
            }
        if "contradictions" in props:  # active contradiction search
            return {
                "contradictions": self._contradictions
                if self._contradictions is not None
                else []
            }
        if "conflicts" in props:
            return {"conflicts": self._conflicts if self._conflicts is not None else []}
        if "gaps" in props:
            return {"gaps": self._gaps if self._gaps is not None else []}
        if "claims" in props:
            return {
                "claims": self._claims
                if self._claims is not None
                else [{"text": "Claim A", "source_indices": [0], "conflicting": False}]
            }
        if "options" in props:  # rd_analysis comparison
            return {
                "criteria": ["Offline"],
                "options": [
                    {"name": "OptX", "description": "d", "pros": ["fast"], "cons": ["new"],
                     "risks": ["r"], "scores": [{"criterion": "Offline", "rating": "strong"}]},
                ],
            }
        if "recommended_option" in props:
            return {"recommended_option": "OptX", "rationale": "best", "why": "reasons",
                    "confidence": 80, "alternatives": ["OptY"], "risks": ["r1"]}
        if "roadmap" in props:
            return {"proof_of_concept": "poc", "roadmap": [{"step": "S1", "detail": "d"}]}
        # findings extraction
        return {"summary": "sum", "findings": ["finding one", "finding two"]}

    async def stream(self, prompt, system=None):  # pragma: no cover
        yield await self.generate(prompt, system=system)

    async def embed(self, texts):
        return [_fake_vec(t) for t in texts]

    async def embeddings_available(self):
        return True

    async def health_check(self):
        return True

    async def list_models(self):
        return ["fake"]


def make_docx_bytes(blocks: list[tuple[str, str]]) -> bytes:
    """Build a real .docx in memory. blocks: list of ('h'|'p', text)."""
    import io

    from docx import Document as Docx

    buf = io.BytesIO()
    d = Docx()
    for style, text in blocks:
        if style == "h":
            d.add_heading(text, level=1)
        else:
            d.add_paragraph(text)
    d.save(buf)
    return buf.getvalue()


def make_pdf_bytes(pages: list[list[str]]) -> bytes:
    """Build a real, text-extractable .pdf in memory. pages: list of lists of lines."""
    import io

    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    for lines in pages:
        y = 750
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def make_collected(source_type: str, url: str, *, reliability=80.0, findings=None, meta=None):
    from app.agents.common import CollectedSource

    return CollectedSource(
        title=f"{source_type} src",
        url=url,
        content="content",
        summary="summary",
        reliability_score=reliability,
        relevance_score=70.0,
        source_type=source_type,
        published_date="2025-01-01",
        findings=findings if findings is not None else [f"{source_type} finding"],
        meta=meta or {},
    )


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
async def reset_db():
    """Recreate all tables for isolation. Requested by any DB-touching test."""
    from app import models  # noqa: F401  (register mappers)
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db(reset_db):
    """A session against the freshly reset database."""
    from app.database import SessionLocal

    async with SessionLocal() as session:
        yield session


async def register_user(client, email="tester@example.com", password="password123", name="Tester"):
    """Register an account and return (token, user_dict)."""
    r = await client.post(
        "/auth/register", json={"email": email, "password": password, "name": name}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["access_token"], body["user"]


@pytest.fixture
async def client(reset_db):
    """An ASGI client pre-authenticated as a default user.

    Auth is enabled in the suite, so this registers a user and attaches its bearer
    token by default. Tests exercising cross-user isolation override the
    Authorization header per request (or register a second user).
    """
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        token, user = await register_user(c)
        c.headers["Authorization"] = f"Bearer {token}"
        c.default_user = user  # type: ignore[attr-defined]  (convenience for tests)
        yield c


@pytest.fixture
async def anon_client(reset_db):
    """An ASGI client with no credentials (for testing 401 enforcement)."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def patch_pipeline(monkeypatch):
    """Patch the orchestrator's provider + collection so a full run needs no network."""
    import asyncio

    import app.orchestration.orchestrator as orch

    provider = FakeProvider()

    async def fake_collect(
        source_type, prov, tavily, settings, *, question, search_query,
        recency_days=None, project_id="",
    ):
        return [make_collected(source_type, f"https://{source_type}.example/x")]

    monkeypatch.setattr(orch, "get_provider", lambda: provider)
    monkeypatch.setattr(orch.dispatch, "collect", fake_collect)
    # The module-level DB lock is bound to whichever loop first used it; rebind it to
    # this test's loop (pytest-asyncio uses a fresh loop per test).
    monkeypatch.setattr(orch, "_db_lock", asyncio.Lock())
    # Knowledge indexing uses its own provider handle.
    import app.knowledge.service as ksvc
    monkeypatch.setattr(ksvc, "get_provider", lambda: provider)
    return provider


async def run_to_completion(project_id: str, *, timeout: float = 15.0) -> None:
    """Wait for a background research run to finish."""
    import asyncio

    from app.services.research_service import manager

    elapsed = 0.0
    while manager.is_active(project_id) and elapsed < timeout:
        await asyncio.sleep(0.05)
        elapsed += 0.05
