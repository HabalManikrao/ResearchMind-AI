"""Scheduled research CRUD, access control, and firing."""
from sqlalchemy import select

from app.models import ResearchProject, ScheduledResearch
from app.services import scheduler as sched_svc
from tests.conftest import register_user, run_to_completion


async def test_create_and_list_schedule(client):
    r = await client.post(
        "/schedules",
        json={"query": "weekly AI news", "kind": "interval", "interval_minutes": 60},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "interval"
    assert body["interval_minutes"] == 60
    assert body["enabled"] is True

    listed = await client.get("/schedules")
    assert len(listed.json()) == 1


async def test_interval_requires_interval_minutes(client):
    r = await client.post("/schedules", json={"query": "topic", "kind": "interval"})
    assert r.status_code == 422


async def test_interval_floored_to_minimum(client):
    # min_schedule_interval_minutes defaults to 15.
    r = await client.post(
        "/schedules",
        json={"query": "too frequent", "kind": "interval", "interval_minutes": 1},
    )
    assert r.status_code == 201
    assert r.json()["interval_minutes"] == 15


async def test_once_requires_start_at(client):
    r = await client.post("/schedules", json={"query": "one off", "kind": "once"})
    assert r.status_code == 422


async def test_update_and_delete_schedule(client):
    pid = (await client.post(
        "/schedules",
        json={"query": "topic", "kind": "interval", "interval_minutes": 30},
    )).json()["id"]

    upd = await client.patch(f"/schedules/{pid}", json={"enabled": False})
    assert upd.status_code == 200
    assert upd.json()["enabled"] is False

    dele = await client.delete(f"/schedules/{pid}")
    assert dele.status_code == 200
    assert (await client.get("/schedules")).json() == []


async def test_schedule_scoped_to_user(client, anon_client):
    sid = (await client.post(
        "/schedules",
        json={"query": "private", "kind": "interval", "interval_minutes": 30},
    )).json()["id"]

    token_b, _ = await register_user(anon_client, email="sb@example.com")
    r = await anon_client.get(
        f"/schedules/{sid}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404
    listed = await anon_client.get(
        "/schedules", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert listed.json() == []


async def test_requires_auth(anon_client):
    assert (await anon_client.get("/schedules")).status_code == 401


async def test_run_due_once_spawns_and_advances(client, patch_pipeline, db):
    # next_run_at defaults to now -> immediately due.
    sid = (await client.post(
        "/schedules",
        json={"query": "auto run", "kind": "interval", "interval_minutes": 30},
    )).json()["id"]

    fired = await sched_svc.run_due_once()
    assert fired == 1

    sched = await db.get(ScheduledResearch, sid)
    assert sched.run_count == 1
    assert sched.last_project_id is not None
    assert sched.next_run_at > sched.last_run_at  # advanced by the interval

    # The spawned project is owned by the schedule's user.
    proj = await db.get(ResearchProject, sched.last_project_id)
    assert proj.user_id == client.default_user["id"]
    await run_to_completion(sched.last_project_id)


async def test_once_schedule_disables_after_firing(client, patch_pipeline, db):
    from datetime import datetime, timezone

    sched = ScheduledResearch(
        user_id=client.default_user["id"], title="One off", query="q",
        kind="once", next_run_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    db.add(sched)
    await db.commit()

    fired = await sched_svc.run_due_once()
    assert fired == 1

    refreshed = await db.get(ScheduledResearch, sched.id)
    await db.refresh(refreshed)
    assert refreshed.enabled is False
    if refreshed.last_project_id:
        await run_to_completion(refreshed.last_project_id)


async def test_run_now_does_not_advance_cadence(client, patch_pipeline, db):
    r = await client.post(
        "/schedules",
        json={"query": "manual", "kind": "interval", "interval_minutes": 30},
    )
    sid = r.json()["id"]
    before = (await client.get(f"/schedules/{sid}")).json()["next_run_at"]

    rn = await client.post(f"/schedules/{sid}/run-now")
    assert rn.status_code == 200

    after = (await client.get(f"/schedules/{sid}")).json()
    assert after["next_run_at"] == before  # cadence untouched
    assert after["run_count"] == 1
    if after["last_project_id"]:
        await run_to_completion(after["last_project_id"])
