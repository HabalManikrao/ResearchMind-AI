"""Knowledge Graph API (#7, spec §23, §24, §30, §33): reads, pagination, depth clamp,
ownership/isolation. Entities are seeded directly (owned by the test user) to exercise the
API layer without driving a full pipeline."""
import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Claim,
    ClaimStatus,
    KgClaimLink,
    KgEntity,
    KgMention,
    KgRelationship,
    ResearchProject,
    Source,
)
from app.models.enums import ProjectStatus


async def _entity(user_id, name, etype="technology", mentions=5, aliases=None):
    async with SessionLocal() as db:
        e = KgEntity(user_id=user_id, canonical_name=name,
                     normalized_name=name.lower(), entity_type=etype,
                     description=f"{name} description", aliases=aliases or [],
                     mention_count=mentions)
        db.add(e)
        await db.commit()
        await db.refresh(e)
        return e.id


async def _relationship(user_id, subj, pred, obj):
    async with SessionLocal() as db:
        r = KgRelationship(user_id=user_id, subject_entity_id=subj, predicate=pred,
                           object_entity_id=obj, confidence=0.6, provenance_kind="derived")
        db.add(r)
        await db.commit()
        await db.refresh(r)
        return r.id


async def _mention(user_id, entity_id, target_type, target_id, project_id=None):
    async with SessionLocal() as db:
        db.add(KgMention(user_id=user_id, entity_id=entity_id, target_type=target_type,
                         target_id=target_id, project_id=project_id, role="mentions"))
        await db.commit()


# --------------------------------------------------------------------------- #
# Search / list
# --------------------------------------------------------------------------- #
async def test_entity_search_and_type_filter(client):
    uid = client.default_user["id"]
    await _entity(uid, "Unreal Engine 5", "software", mentions=9, aliases=["UE5"])
    await _entity(uid, "Unity", "software", mentions=3)
    await _entity(uid, "OpenAI", "company", mentions=2)

    # List all — ordered by mention_count desc.
    r = await client.get("/knowledge/entities")
    assert r.status_code == 200
    names = [e["canonical_name"] for e in r.json()]
    assert names[0] == "Unreal Engine 5"

    # Search by name.
    r = await client.get("/knowledge/entities?q=unreal")
    assert [e["canonical_name"] for e in r.json()] == ["Unreal Engine 5"]

    # Search by alias (aliases stored as JSON, matched as text).
    r = await client.get("/knowledge/entities?q=UE5")
    assert any(e["canonical_name"] == "Unreal Engine 5" for e in r.json())

    # Filter by type.
    r = await client.get("/knowledge/entities?type=company")
    assert [e["canonical_name"] for e in r.json()] == ["OpenAI"]


async def test_pagination(client):
    uid = client.default_user["id"]
    for i in range(5):
        await _entity(uid, f"Ent{i}", mentions=10 - i)
    r = await client.get("/knowledge/entities?limit=2&offset=0")
    assert len(r.json()) == 2
    r2 = await client.get("/knowledge/entities?limit=2&offset=2")
    assert len(r2.json()) == 2
    assert r.json()[0]["id"] != r2.json()[0]["id"]


# --------------------------------------------------------------------------- #
# Detail / claims / graph / history
# --------------------------------------------------------------------------- #
async def test_entity_detail_with_related(client):
    uid = client.default_user["id"]
    a = await _entity(uid, "Unreal Engine 5")
    b = await _entity(uid, "Nanite")
    await _relationship(uid, a, "related_to", b)
    r = await client.get(f"/knowledge/entities/{a}")
    assert r.status_code == 200
    body = r.json()
    assert body["entity"]["canonical_name"] == "Unreal Engine 5"
    assert len(body["related"]) == 1
    assert body["related"][0]["entity"]["canonical_name"] == "Nanite"


async def test_entity_current_vs_historical_claims(client):
    uid = client.default_user["id"]
    ent = await _entity(uid, "Lumen")
    async with SessionLocal() as db:
        proj = ResearchProject(user_id=uid, title="t", query="q",
                               status=ProjectStatus.COMPLETED, run_number=1)
        db.add(proj)
        await db.flush()
        proj.root_id = proj.id
        c_old = Claim(project_id=proj.id, text="Lumen was slow.", status=ClaimStatus.VERIFIED,
                      confidence=60.0, confidence_meta={})
        c_new = Claim(project_id=proj.id, text="Lumen is fast now.", status=ClaimStatus.VERIFIED,
                      confidence=85.0, confidence_meta={})
        db.add_all([c_old, c_new])
        await db.flush()
        # c_new supersedes c_old → c_old is historical.
        db.add(KgClaimLink(user_id=uid, subject_claim_id=c_new.id, predicate="supersedes",
                           object_claim_id=c_old.id, project_id=proj.id))
        old_id, new_id = c_old.id, c_new.id
        await db.commit()
    await _mention(uid, ent, "claim", old_id)
    await _mention(uid, ent, "claim", new_id)

    r = await client.get(f"/knowledge/entities/{ent}/claims?scope=current")
    assert [c["claim_id"] for c in r.json()] == [new_id]
    r = await client.get(f"/knowledge/entities/{ent}/claims?scope=historical")
    assert [c["claim_id"] for c in r.json()] == [old_id]
    r = await client.get(f"/knowledge/entities/{ent}/claims?scope=all")
    assert {c["claim_id"] for c in r.json()} == {old_id, new_id}


async def test_entity_graph_depth_is_clamped(client):
    uid = client.default_user["id"]
    a = await _entity(uid, "A")
    b = await _entity(uid, "B")
    await _relationship(uid, a, "related_to", b)
    r = await client.get(f"/knowledge/entities/{a}/graph?depth=5")
    assert r.status_code == 200
    body = r.json()
    assert body["depth"] <= 2  # hard clamp (kg_max_graph_depth)
    assert {n["canonical_name"] for n in body["nodes"]} == {"A", "B"}
    assert len(body["edges"]) == 1


async def test_entity_history(client):
    uid = client.default_user["id"]
    ent = await _entity(uid, "Lumen")
    async with SessionLocal() as db:
        proj = ResearchProject(user_id=uid, title="Lumen run", query="q",
                               status=ProjectStatus.COMPLETED, run_number=1)
        db.add(proj)
        await db.flush()
        pid = proj.id
        await db.commit()
    await _mention(uid, ent, "project", pid, project_id=pid)
    r = await client.get(f"/knowledge/entities/{ent}/history")
    assert r.status_code == 200
    assert any(i["kind"] == "observed" for i in r.json()["items"])


async def test_relationship_detail(client):
    uid = client.default_user["id"]
    a = await _entity(uid, "A")
    b = await _entity(uid, "B")
    rid = await _relationship(uid, a, "alternative_to", b)
    r = await client.get(f"/knowledge/relationships/{rid}")
    assert r.status_code == 200
    assert r.json()["predicate"] == "alternative_to"


# --------------------------------------------------------------------------- #
# Errors / auth / isolation (spec §24)
# --------------------------------------------------------------------------- #
async def test_invalid_entity_id_404(client):
    assert (await client.get("/knowledge/entities/nope")).status_code == 404
    assert (await client.get("/knowledge/relationships/nope")).status_code == 404


async def test_requires_auth(anon_client):
    assert (await anon_client.get("/knowledge/entities")).status_code == 401
    assert (await anon_client.get("/knowledge/entities/x")).status_code == 401


async def test_cross_user_entity_is_not_visible(client):
    """A second user's entity must 404 and never appear in the first user's list."""
    from tests.conftest import register_user
    import httpx
    from app.main import app

    other_id = None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        token, ouser = await register_user(other, email="other@example.com")
        other.headers["Authorization"] = f"Bearer {token}"
        other_entity = await _entity(ouser["id"], "Secret Entity")
        # Owner can see it.
        assert (await other.get(f"/knowledge/entities/{other_entity}")).status_code == 200

    # The first user cannot.
    assert (await client.get(f"/knowledge/entities/{other_entity}")).status_code == 404
    listing = await client.get("/knowledge/entities")
    assert all(e["canonical_name"] != "Secret Entity" for e in listing.json())
