"""Authentication and per-user access control."""
from app.models import ProjectStatus, ResearchProject
from tests.conftest import register_user


async def test_register_returns_token_and_user(anon_client):
    r = await anon_client.post(
        "/auth/register",
        json={"email": "a@example.com", "password": "password123", "name": "A"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "a@example.com"
    assert body["user"]["is_admin"] is True  # first account is admin


async def test_register_rejects_duplicate_email(anon_client):
    await register_user(anon_client, email="dupe@example.com")
    r = await anon_client.post(
        "/auth/register",
        json={"email": "dupe@example.com", "password": "password123"},
    )
    assert r.status_code == 409


async def test_register_rejects_short_password(anon_client):
    r = await anon_client.post(
        "/auth/register", json={"email": "x@example.com", "password": "short"}
    )
    assert r.status_code == 422


async def test_login_success_and_failure(anon_client):
    await register_user(anon_client, email="log@example.com", password="password123")

    ok = await anon_client.post(
        "/auth/login", json={"email": "log@example.com", "password": "password123"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await anon_client.post(
        "/auth/login", json={"email": "log@example.com", "password": "wrongpass"}
    )
    assert bad.status_code == 401

    missing = await anon_client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "password123"}
    )
    assert missing.status_code == 401


async def test_me_returns_current_user(client):
    r = await client.get("/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "tester@example.com"


async def test_protected_endpoints_require_auth(anon_client):
    for method, path in [
        ("get", "/research"),
        ("post", "/research"),
        ("get", "/knowledge/status"),
        ("get", "/monitoring/stats"),
        ("get", "/auth/me"),
    ]:
        resp = await getattr(anon_client, method)(
            path, **({"json": {"query": "hello world"}} if method == "post" else {})
        )
        assert resp.status_code == 401, f"{method} {path} -> {resp.status_code}"


async def test_user_cannot_access_another_users_project(client, anon_client):
    # User A (the default `client`) creates a project.
    pid = (await client.post(
        "/research", json={"query": "user A private topic", "auto_start": False}
    )).json()["id"]

    # User B registers and tries to read it.
    token_b, _ = await register_user(anon_client, email="b@example.com")
    r = await anon_client.get(
        f"/research/{pid}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404  # hidden, not merely forbidden

    # ...and it does not appear in B's list.
    listed = await anon_client.get(
        "/research", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert all(p["id"] != pid for p in listed.json())


async def test_list_scoped_to_owner(client, anon_client):
    await client.post("/research", json={"query": "owned by A", "auto_start": False})
    token_b, _ = await register_user(anon_client, email="b2@example.com")
    listed = await anon_client.get(
        "/research", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert listed.json() == []  # B owns nothing


async def test_legacy_unowned_project_visible_to_any_user(client, db):
    # A project created before auth has no owner and stays readable.
    proj = ResearchProject(title="Legacy", query="q", status=ProjectStatus.CREATED)
    db.add(proj)
    await db.commit()
    r = await client.get(f"/research/{proj.id}")
    assert r.status_code == 200


async def test_invalid_token_rejected(anon_client):
    r = await anon_client.get(
        "/research", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert r.status_code == 401
