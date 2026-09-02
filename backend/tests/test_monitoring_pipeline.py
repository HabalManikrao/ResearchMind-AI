"""End-to-end monitoring pipeline (#6, spec §7, §11, §17, §20): the two-tier check.

Drives ``run_monitor_check`` directly (the scheduler is off in the suite) with faked
collection + connectivity, so no network is touched. Covers: no-change suppression, an
escalated meaningful change → notification, dedup across consecutive checks, and offline
correctness (an incomplete external check is never reported as "no changes").
"""
import pytest
from sqlalchemy import select

import app.orchestration.orchestrator as orch
import app.services.connectivity as conn
import app.services.research_monitor as rm
from app.models import MonitorCheck, Notification, ResearchMonitor
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from app.services.research_diff import ResearchDiff
from tests.conftest import run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(
            overall=ONLINE, internet=True, search_provider=True,
            ollama=True, qdrant=True, database=True,
        )
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _baseline(client) -> str:
    r = await client.post("/research", json={"query": "compare vector databases",
                                             "sources_enabled": ["web"], "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


async def _make_monitor(client, db, project_id, **over) -> str:
    body = {"frequency": "daily", "notify_policy": "all", **over}
    r = await client.post(f"/research/{project_id}/monitor", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _critical_diff(*, recommendation_reversed=True) -> ResearchDiff:
    rec = (
        {"kind": "reversed", "old": {"option": "OptX"}, "new": {"option": "OptY"}}
        if recommendation_reversed
        else {"kind": "unchanged", "old": None, "new": None}
    )
    return ResearchDiff(
        old_run={}, new_run={}, sources={"items": []}, claims={"items": []},
        confidence={}, recommendation=rec, documents={"items": []},
    )


async def _monitor_alerts(db, user_id) -> list[Notification]:
    return (
        await db.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.type == "monitor_alert")
        )
    ).scalars().all()


# --------------------------------------------------------------------------- #
# No meaningful change → suppressed, no notification (spec §11).
# --------------------------------------------------------------------------- #
async def test_no_change_is_suppressed(client, patch_pipeline, db):
    pid = await _baseline(client)
    mid = await _make_monitor(client, db, pid)

    # The cheap probe re-collects the same source (same url/content) → nothing new.
    result = await rm.run_monitor_check(mid)
    assert result["status"] == "no_change"

    alerts = await _monitor_alerts(db, client.default_user["id"])
    assert alerts == []  # never spam "nothing changed" (spec §11)

    monitor = await db.get(ResearchMonitor, mid)
    assert monitor.last_status == "no_change"
    assert monitor.consecutive_failures == 0
    checks = (await db.execute(select(MonitorCheck).where(MonitorCheck.monitor_id == mid))).scalars().all()
    assert len(checks) == 1 and checks[0].status == "no_change"


# --------------------------------------------------------------------------- #
# A meaningful change → deep verification → notification (spec §7, §12).
# --------------------------------------------------------------------------- #
async def test_meaningful_change_escalates_and_notifies(client, patch_pipeline, db, monkeypatch):
    pid = await _baseline(client)
    mid = await _make_monitor(client, db, pid)

    # Force Stage-1 to escalate (a candidate-significant source appeared)…
    async def escalating_probe(monitor, baseline):
        p = rm._Probe()
        p.escalate = True
        p.live = 1
        return p
    monkeypatch.setattr(rm, "_cheap_probe", escalating_probe)
    # …and pin the deep-diff to a recommendation reversal (the diff engine itself is
    # covered by test_research_diff.py — here we test the monitoring reaction to it).
    async def fake_diff(old_id, new_id):
        return _critical_diff()
    monkeypatch.setattr(rm.research_diff, "diff_runs", fake_diff)

    result = await rm.run_monitor_check(mid)
    assert result["status"] == "changes"
    assert result["notifiable"] == 1

    alerts = await _monitor_alerts(db, client.default_user["id"])
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert alerts[0].data["baseline_run_id"] == pid
    assert alerts[0].data["new_run_id"] and alerts[0].data["new_run_id"] != pid

    monitor = await db.get(ResearchMonitor, mid)
    assert monitor.last_status == "changes"
    assert monitor.last_run_id == alerts[0].data["new_run_id"]  # baseline advanced


# --------------------------------------------------------------------------- #
# The same change across consecutive checks is not re-notified (spec §17).
# --------------------------------------------------------------------------- #
async def test_repeated_change_is_deduplicated(client, patch_pipeline, db, monkeypatch):
    pid = await _baseline(client)
    mid = await _make_monitor(client, db, pid)

    async def escalating_probe(monitor, baseline):
        p = rm._Probe(); p.escalate = True; p.live = 1
        return p
    monkeypatch.setattr(rm, "_cheap_probe", escalating_probe)

    async def fake_diff(old_id, new_id):
        return _critical_diff()  # identical change each time → identical dedup key
    monkeypatch.setattr(rm.research_diff, "diff_runs", fake_diff)

    first = await rm.run_monitor_check(mid)
    second = await rm.run_monitor_check(mid)

    assert first["status"] == "changes"
    assert second["status"] == "suppressed"  # same change, already delivered
    alerts = await _monitor_alerts(db, client.default_user["id"])
    assert len(alerts) == 1  # notified exactly once


# --------------------------------------------------------------------------- #
# Offline correctness: an incomplete external check is NOT "no changes" (spec §20).
# --------------------------------------------------------------------------- #
async def test_incomplete_external_check_is_degraded_not_no_change(
    client, patch_pipeline, db, monkeypatch
):
    pid = await _baseline(client)
    # live_only → cache is never consulted, so a live failure is a hard, honest failure.
    mid = await _make_monitor(client, db, pid, source_policy="live_only")

    # Break live collection: the external probe now genuinely fails.
    async def failing_collect(source_type, prov, tavily, settings, *, question,
                              search_query, recency_days=None, project_id=""):
        raise RuntimeError("provider unreachable")
    monkeypatch.setattr(orch.dispatch, "collect", failing_collect)

    result = await rm.run_monitor_check(mid)
    assert result["status"] == "degraded"

    alerts = await _monitor_alerts(db, client.default_user["id"])
    assert alerts == []  # must NOT claim "no changes" on an incomplete check
    monitor = await db.get(ResearchMonitor, mid)
    assert monitor.last_status == "degraded"
    checks = (await db.execute(select(MonitorCheck).where(MonitorCheck.monitor_id == mid))).scalars().all()
    assert len(checks) == 1 and checks[0].status == "degraded"
    assert checks[0].new_run_id is None  # no expensive deep run on a degraded check
