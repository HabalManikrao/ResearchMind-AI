"""In-app notifications: creation on run completion, access control, read state."""
from app.models import Notification
from tests.conftest import register_user, run_to_completion


async def _seed_notification(db, user_id, *, read=False, title="Test"):
    n = Notification(user_id=user_id, type="info", title=title, read=read)
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n.id


async def test_notification_created_on_completion(client, patch_pipeline):
    pid = (await client.post(
        "/research", json={"query": "notify me", "auto_start": True}
    )).json()["id"]
    await run_to_completion(pid)

    notes = (await client.get("/notifications")).json()
    types = {n["type"] for n in notes}
    assert "research_completed" in types
    assert any(n["project_id"] == pid for n in notes)


async def test_unread_count_and_mark_read(client, db):
    nid = await _seed_notification(db, client.default_user["id"])
    assert (await client.get("/notifications/unread-count")).json()["unread"] == 1

    r = await client.post(f"/notifications/{nid}/read")
    assert r.status_code == 200
    assert (await client.get("/notifications/unread-count")).json()["unread"] == 0


async def test_read_all(client, db):
    uid = client.default_user["id"]
    await _seed_notification(db, uid)
    await _seed_notification(db, uid)
    assert (await client.get("/notifications/unread-count")).json()["unread"] == 2

    await client.post("/notifications/read-all")
    assert (await client.get("/notifications/unread-count")).json()["unread"] == 0


async def test_unread_only_filter(client, db):
    uid = client.default_user["id"]
    await _seed_notification(db, uid, read=True, title="old")
    await _seed_notification(db, uid, read=False, title="new")
    unread = (await client.get("/notifications", params={"unread_only": True})).json()
    assert len(unread) == 1
    assert unread[0]["title"] == "new"


async def test_notifications_scoped_to_user(client, anon_client, db):
    await _seed_notification(db, client.default_user["id"], title="A's note")
    token_b, user_b = await register_user(anon_client, email="nb@example.com")
    listed = await anon_client.get(
        "/notifications", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert listed.json() == []


async def test_delete_notification(client, db):
    nid = await _seed_notification(db, client.default_user["id"])
    r = await client.delete(f"/notifications/{nid}")
    assert r.status_code == 200
    assert (await client.get("/notifications")).json() == []


async def test_requires_auth(anon_client):
    assert (await anon_client.get("/notifications")).status_code == 401
