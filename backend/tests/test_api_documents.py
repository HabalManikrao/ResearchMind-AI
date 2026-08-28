"""Document API: upload (multipart), process, list/status/chunks/search/delete, security."""
import asyncio

import pytest

import app.documents.service as svc
from tests.conftest import FakeProvider, make_docx_bytes, register_user


@pytest.fixture
def doc_provider(monkeypatch):
    monkeypatch.setattr(svc, "get_provider", lambda: FakeProvider())


async def _project(client) -> str:
    r = await client.post(
        "/research",
        json={"query": "docs test", "sources_enabled": ["documents"], "auto_start": False},
    )
    return r.json()["id"]


async def _upload(client, pid, name, content, headers=None):
    return await client.post(
        "/documents",
        data={"project_id": pid},
        files={"file": (name, content, "application/octet-stream")},
        headers=headers or {},
    )


async def _wait_ready(client, doc_id, timeout=10.0):
    elapsed = 0.0
    status = {}
    while elapsed < timeout:
        status = (await client.get(f"/documents/{doc_id}/status")).json()
        if status["status"] in ("ready", "failed"):
            return status
        await asyncio.sleep(0.05)
        elapsed += 0.05
    return status


async def test_upload_process_and_search(client, doc_provider):
    pid = await _project(client)
    content = make_docx_bytes(
        [("h", "Podman"), ("p", "Podman provides a Docker-compatible CLI.")]
    )
    r = await _upload(client, pid, "podman.docx", content)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["original_filename"] == "podman.docx"
    assert "storage_path" not in doc  # internal path never exposed

    st = await _wait_ready(client, doc["id"])
    assert st["status"] == "ready", st

    chunks = (await client.get(f"/documents/{doc['id']}/chunks")).json()
    assert chunks

    res = await client.post(
        "/documents/search", json={"project_id": pid, "query": "Docker compatible CLI"}
    )
    assert res.status_code == 200
    passages = res.json()
    assert passages and any("Docker-compatible" in p["text"] for p in passages)


async def test_upload_rejects_bad_type_and_mismatch(client, doc_provider):
    pid = await _project(client)
    assert (await _upload(client, pid, "evil.exe", b"MZ\x90\x00")).status_code == 400
    assert (await _upload(client, pid, "fake.pdf", b"not a pdf at all")).status_code == 400


async def test_cross_user_and_cross_project_isolation(client, doc_provider):
    pid = await _project(client)
    content = make_docx_bytes([("p", "secret content")])
    doc = (await _upload(client, pid, "s.docx", content)).json()

    token2, _ = await register_user(client, email="two@example.com")
    h = {"Authorization": f"Bearer {token2}"}
    assert (await client.get(f"/documents/{doc['id']}", headers=h)).status_code == 404
    assert (await client.get(f"/documents?project_id={pid}", headers=h)).status_code == 404
    # user2 cannot upload into user1's project
    assert (await _upload(client, pid, "x.docx", content, headers=h)).status_code == 404
    # user2 cannot search user1's project
    r = await client.post(
        "/documents/search", json={"project_id": pid, "query": "secret"}, headers=h
    )
    assert r.status_code == 404


async def test_delete_document(client, doc_provider):
    pid = await _project(client)
    content = make_docx_bytes([("p", "to be deleted")])
    doc = (await _upload(client, pid, "d.docx", content)).json()
    await _wait_ready(client, doc["id"])
    assert (await client.delete(f"/documents/{doc['id']}")).status_code == 200
    assert (await client.get(f"/documents/{doc['id']}")).status_code == 404
