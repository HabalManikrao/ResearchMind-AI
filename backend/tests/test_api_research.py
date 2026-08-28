from app.models import ProjectStatus, ResearchProject


async def test_create_and_get_research(client):
    r = await client.post("/research", json={"query": "compare vector dbs", "auto_start": False})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["status"] == "created"

    got = await client.get(f"/research/{pid}")
    assert got.status_code == 200
    assert got.json()["query"] == "compare vector dbs"


async def test_list_research(client):
    await client.post("/research", json={"query": "topic one", "auto_start": False})
    await client.post("/research", json={"query": "topic two", "auto_start": False})
    r = await client.get("/research")
    assert r.status_code == 200
    assert len(r.json()) == 2


async def test_get_missing_returns_404(client):
    r = await client.get("/research/does-not-exist")
    assert r.status_code == 404


async def test_create_validation_rejects_short_query(client):
    r = await client.post("/research", json={"query": "x", "auto_start": False})
    assert r.status_code == 422


async def test_add_and_list_questions(client):
    pid = (await client.post("/research", json={"query": "a topic", "auto_start": False})).json()["id"]
    r = await client.post(f"/research/{pid}/questions", json={"text": "A question?", "priority": 1})
    assert r.status_code == 201
    listed = await client.get(f"/research/{pid}/questions")
    assert len(listed.json()) == 1


async def test_export_requires_ready_report(client):
    pid = (await client.post("/research", json={"query": "a topic", "auto_start": False})).json()["id"]
    r = await client.get(f"/research/{pid}/export", params={"format": "md"})
    assert r.status_code == 409  # report not ready


async def test_export_markdown_when_report_present(client, db):
    proj = ResearchProject(
        title="Report Ready", query="q", status=ProjectStatus.COMPLETED,
        report_markdown="# Title\n\nBody", report_meta={},
    )
    db.add(proj)
    await db.commit()
    r = await client.get(f"/research/{proj.id}/export", params={"format": "md"})
    assert r.status_code == 200
    assert r.content.decode("utf-8") == "# Title\n\nBody"
    assert "attachment" in r.headers["content-disposition"]


async def test_export_rejects_bad_format(client, db):
    proj = ResearchProject(title="t", query="q", status=ProjectStatus.COMPLETED, report_markdown="# x")
    db.add(proj)
    await db.commit()
    r = await client.get(f"/research/{proj.id}/export", params={"format": "exe"})
    assert r.status_code == 422  # pattern validation


async def test_pause_resume_stop_when_not_running(client):
    pid = (await client.post("/research", json={"query": "a topic", "auto_start": False})).json()["id"]
    assert (await client.post(f"/research/{pid}/pause")).json()["ok"] is False
    assert (await client.post(f"/research/{pid}/stop")).json()["ok"] is False
