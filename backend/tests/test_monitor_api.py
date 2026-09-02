"""Research monitoring API (#6, spec §31, §32): CRUD, ownership, isolation, run-now."""
import pytest

import app.services.connectivity as conn
from app.services.connectivity import ConnectivitySnapshot, ONLINE
from tests.conftest import register_user, run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    """Avoid real network probes in the suite (matches the #5 pipeline tests)."""
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(
            overall=ONLINE, internet=True, search_provider=True,
            ollama=True, qdrant=True, database=True,
        )
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _completed_project(client, patch_pipeline, *, query="best vector db") -> str:
    """Create a research project and run it to completion (offline)."""
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    g = await client.get(f"/research/{pid}")
    assert g.json()["status"] == "completed"
    return pid


async def test_cannot_monitor_incomplete_research(client):
    r = await client.post("/research", json={"query": "unfinished topic"})
    pid = r.json()["id"]
    resp = await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    assert resp.status_code == 409  # no completed run to monitor yet


async def test_create_get_update_delete_monitor(client, patch_pipeline):
    pid = await _completed_project(client, patch_pipeline)

    # Create.
    r = await client.post(f"/research/{pid}/monitor",
                          json={"frequency": "weekly", "notify_policy": "important"})
    assert r.status_code == 201, r.text
    mon = r.json()
    assert mon["frequency"] == "weekly"
    assert mon["notify_policy"] == "important"
    assert mon["enabled"] is True
    assert mon["interval_minutes"] == 10080
    assert mon["health"] == "healthy"

    # Get (with history).
    r = await client.get(f"/research/{pid}/monitor")
    assert r.status_code == 200
    assert r.json()["monitor"]["id"] == mon["id"]
    assert r.json()["recent_checks"] == []

    # Update — disable + change policy.
    r = await client.patch(f"/research/{pid}/monitor",
                           json={"enabled": False, "notify_policy": "critical"})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["health"] == "disabled"

    # Delete.
    r = await client.delete(f"/research/{pid}/monitor")
    assert r.status_code == 200
    r = await client.get(f"/research/{pid}/monitor")
    assert r.status_code == 404


async def test_create_is_idempotent_upsert(client, patch_pipeline):
    pid = await _completed_project(client, patch_pipeline)
    r1 = await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    r2 = await client.post(f"/research/{pid}/monitor", json={"frequency": "monthly"})
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]  # same monitor reconfigured, not duplicated
    assert r2.json()["frequency"] == "monthly"


async def test_run_now_launches_without_duplicate_schedule(client, patch_pipeline, monkeypatch):
    pid = await _completed_project(client, patch_pipeline)
    await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})

    launched = []
    monkeypatch.setattr(
        "app.services.research_monitor._launch", lambda mid: launched.append(mid)
    )
    r = await client.post(f"/research/{pid}/monitor/run")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(launched) == 1


async def test_monitor_is_isolated_across_users(client, patch_pipeline):
    """A second user must not see or touch the first user's monitor (spec §32)."""
    pid = await _completed_project(client, patch_pipeline)
    await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})

    # Second user, separate client credentials against the same app.
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        token, _ = await register_user(other, email="intruder@example.com")
        other.headers["Authorization"] = f"Bearer {token}"
        # The other user can't even see the project (404, not 403 — no existence leak).
        assert (await other.get(f"/research/{pid}/monitor")).status_code == 404
        assert (await other.post(f"/research/{pid}/monitor",
                                 json={"frequency": "daily"})).status_code == 404
        assert (await other.delete(f"/research/{pid}/monitor")).status_code == 404


async def test_monitor_requires_auth(anon_client):
    r = await anon_client.get("/research/whatever/monitor")
    assert r.status_code == 401
