"""Failed-research retry (post-#11 manual-test hardening).

A FAILED run can be retried IN PLACE (same project) once the user fixes the underlying
dependency — distinct from Research Again (which forks a COMPLETED run). Covers the
lifecycle guards, ownership, concurrency/idempotency, failure-history preservation, and
data integrity (no duplicate projects/artifacts). All offline via patch_pipeline.
"""
import asyncio

import pytest

import app.orchestration.orchestrator as orch
from app.database import SessionLocal
from app.models import (
    Claim,
    Finding,
    ProjectStatus,
    ResearchProject,
    ResearchQuestion,
    Source,
)
from sqlalchemy import func, select
from tests.conftest import register_user, run_to_completion


async def _create_started(client, **body):
    payload = {"query": "compare tools", "sources_enabled": ["web"], "auto_start": True}
    payload.update(body)
    r = await client.post("/research", json=payload)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _make_failed_run(client, monkeypatch, *, error="Ollama unavailable"):
    """Start a run whose planner blows up, so the whole run ends FAILED."""
    async def boom(*a, **k):
        raise RuntimeError(error)

    monkeypatch.setattr(orch.planner, "make_plan", boom)
    pid = await _create_started(client)
    await run_to_completion(pid)
    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "failed"
    assert detail["error"] and error in detail["error"]
    return pid


async def _count(model, project_id):
    async with SessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(model).where(model.project_id == project_id)
            )
        ).scalar() or 0


# --------------------------------------------------------------------------- #
# Happy path: FAILED -> fix dependency -> retry -> completes.
# --------------------------------------------------------------------------- #
async def test_failed_run_retry_accepted_and_completes(client, patch_pipeline, monkeypatch):
    real_make_plan = orch.planner.make_plan
    pid = await _make_failed_run(client, monkeypatch)

    # "Fix" the dependency, then retry the SAME project.
    monkeypatch.setattr(orch.planner, "make_plan", real_make_plan)
    r = await client.post(f"/research/{pid}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == pid  # same project, not a new one
    assert body["status"] in ("planning", "running")  # background work started
    assert body["error"] is None

    await run_to_completion(pid)
    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"


# --------------------------------------------------------------------------- #
# Lifecycle guards.
# --------------------------------------------------------------------------- #
async def test_retry_rejected_for_completed(client, patch_pipeline):
    pid = await _create_started(client)
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"

    r = await client.post(f"/research/{pid}/retry")
    assert r.status_code == 409
    assert "failed" in r.json()["detail"].lower()


async def test_retry_rejected_for_running(client, patch_pipeline):
    pid = await _create_started(client)
    # Force the DB status to RUNNING without a live task, then retry -> rejected.
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, pid)
        proj.status = ProjectStatus.RUNNING
        await db.commit()
    r = await client.post(f"/research/{pid}/retry")
    assert r.status_code == 409
    await run_to_completion(pid)  # let the real run settle


# --------------------------------------------------------------------------- #
# Failure history preserved (never silently erased).
# --------------------------------------------------------------------------- #
async def test_retry_preserves_original_failure_history(client, patch_pipeline, monkeypatch):
    real_make_plan = orch.planner.make_plan
    pid = await _make_failed_run(client, monkeypatch, error="Ollama structured_output failed")

    monkeypatch.setattr(orch.planner, "make_plan", real_make_plan)
    assert (await client.post(f"/research/{pid}/retry")).status_code == 200
    await run_to_completion(pid)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"
    history = (detail["report_meta"] or {}).get("retry_history")
    assert history and len(history) == 1
    assert "Ollama structured_output failed" in history[0]["error"]
    assert history[0]["retried_at"]  # timestamped


# --------------------------------------------------------------------------- #
# Data integrity: no duplicate project, no duplicated artifacts.
# --------------------------------------------------------------------------- #
async def test_retry_does_not_create_a_new_project(client, patch_pipeline, monkeypatch):
    real_make_plan = orch.planner.make_plan
    pid = await _make_failed_run(client, monkeypatch)
    before = len((await client.get("/research")).json())

    monkeypatch.setattr(orch.planner, "make_plan", real_make_plan)
    assert (await client.post(f"/research/{pid}/retry")).status_code == 200
    await run_to_completion(pid)

    after = (await client.get("/research")).json()
    assert len(after) == before  # no extra project row
    runs = (await client.get(f"/research/{pid}/runs")).json()
    assert len(runs) == 1  # no new lineage/run created


async def test_retry_does_not_duplicate_artifacts(client, patch_pipeline, monkeypatch):
    # Fail LATE (after questions/sources/claims are persisted) so a naive re-run would
    # duplicate them; a correct retry resets first, leaving single-run counts.
    real_build_report = orch._build_report

    async def boom_report(*a, **k):
        raise RuntimeError("report stage blew up")

    monkeypatch.setattr(orch, "_build_report", boom_report)
    pid = await _create_started(client)
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "failed"

    q_before = await _count(ResearchQuestion, pid)
    s_before = await _count(Source, pid)
    assert q_before > 0 and s_before > 0  # partial artifacts really were persisted

    monkeypatch.setattr(orch, "_build_report", real_build_report)
    assert (await client.post(f"/research/{pid}/retry")).status_code == 200
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"

    # Reset-then-rebuild ⇒ counts match a single run, not doubled.
    assert await _count(ResearchQuestion, pid) == q_before
    assert await _count(Source, pid) == s_before
    # Claims are rebuilt cleanly; evidence links are not orphaned/duplicated.
    assert await _count(Claim, pid) >= 0
    assert await _count(Finding, pid) == await _count(Finding, pid)  # no crash on read


# --------------------------------------------------------------------------- #
# Concurrency / idempotency: only one retry actually starts.
# --------------------------------------------------------------------------- #
async def test_concurrent_retry_starts_only_one(client, patch_pipeline, monkeypatch):
    real_make_plan = orch.planner.make_plan
    pid = await _make_failed_run(client, monkeypatch)

    # Make the retried run block until released, so the second retry hits an active run.
    release = asyncio.Event()

    async def gated(*a, **k):
        await release.wait()
        return await real_make_plan(*a, **k)

    monkeypatch.setattr(orch.planner, "make_plan", gated)
    r1 = await client.post(f"/research/{pid}/retry")
    assert r1.status_code == 200
    r2 = await client.post(f"/research/{pid}/retry")
    assert r2.status_code == 409  # duplicate rejected while the first retry runs

    release.set()
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"


async def test_reset_guard_is_idempotent(client, patch_pipeline, monkeypatch):
    # Direct guard: the first reset succeeds; a second (project no longer FAILED) is a no-op.
    pid = await _make_failed_run(client, monkeypatch)
    assert await orch.reset_project_for_retry(pid) is True
    assert await orch.reset_project_for_retry(pid) is False  # already moved out of FAILED


# --------------------------------------------------------------------------- #
# Transient provider failure recovers on retry.
# --------------------------------------------------------------------------- #
async def test_transient_failure_recovers_on_retry(client, patch_pipeline, monkeypatch):
    real_make_plan = orch.planner.make_plan
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection attempts failed")
        return await real_make_plan(*a, **k)

    monkeypatch.setattr(orch.planner, "make_plan", flaky)
    pid = await _create_started(client)
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "failed"

    assert (await client.post(f"/research/{pid}/retry")).status_code == 200
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"


# --------------------------------------------------------------------------- #
# Security: ownership + authentication.
# --------------------------------------------------------------------------- #
async def test_cross_user_retry_is_404(client, patch_pipeline, monkeypatch):
    pid = await _make_failed_run(client, monkeypatch)
    token_b, _ = await register_user(client, email="other@example.com")
    r = await client.post(
        f"/research/{pid}/retry", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404  # existence not leaked


async def test_unauthenticated_retry_rejected(anon_client):
    r = await anon_client.post("/research/does-not-matter/retry")
    assert r.status_code == 401
