"""Monitor scheduling + service internals (#6, spec §5, §22, §34, §35).

Pure poller/scheduling logic — no pipeline runs. Monitors are inserted directly and
``run_due_once`` is driven with ``_launch`` stubbed so we assert *which* monitors fire and
how the cadence/backoff/concurrency behave, deterministically.
"""
from datetime import datetime, timedelta, timezone

import pytest

import app.services.research_monitor as rm
from app.config import get_settings
from app.models import ResearchMonitor


def _now():
    return datetime.now(timezone.utc)


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _add_monitor(db, *, enabled=True, due_delta_min=-1, interval=1440,
                       last_status="idle", last_checked_at=None) -> ResearchMonitor:
    m = ResearchMonitor(
        user_id="u1", root_id="r-" + str(id(object())), project_id="p1",
        enabled=enabled, frequency="daily", interval_minutes=interval,
        notify_policy="all", next_check_at=_now() + timedelta(minutes=due_delta_min),
        last_status=last_status, last_checked_at=last_checked_at,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


@pytest.fixture(autouse=True)
def _capture_launches(monkeypatch):
    launched: list[str] = []
    monkeypatch.setattr(rm, "_launch", lambda mid: launched.append(mid))
    rm._running.clear()
    yield launched
    rm._running.clear()


def test_frequency_mapping():
    assert rm.frequency_to_minutes("daily") == 1440
    assert rm.frequency_to_minutes("weekly") == 10080
    assert rm.frequency_to_minutes("monthly") == 43200
    assert rm.frequency_to_minutes("bogus") == 1440  # safe default


async def test_due_monitor_is_launched_and_cadence_advances(db, _capture_launches):
    m = await _add_monitor(db, due_delta_min=-5)
    n = await rm.run_due_once()
    assert n == 1
    assert _capture_launches == [m.id]
    # next_check_at advanced ~one interval into the future so it isn't re-launched.
    await db.refresh(m)
    assert _aware(m.next_check_at) > _now()


async def test_disabled_and_future_monitors_do_not_fire(db, _capture_launches):
    await _add_monitor(db, enabled=False, due_delta_min=-5)
    await _add_monitor(db, due_delta_min=120)  # not due yet
    assert await rm.run_due_once() == 0
    assert _capture_launches == []


async def test_already_running_monitor_is_skipped(db, _capture_launches):
    m = await _add_monitor(db, due_delta_min=-5)
    rm._running.add(m.id)  # simulate an in-flight check (spec §35)
    assert await rm.run_due_once() == 0
    assert _capture_launches == []


async def test_concurrency_cap_limits_launches_per_tick(db, _capture_launches, monkeypatch):
    monkeypatch.setattr(get_settings(), "monitor_max_concurrent_checks", 1)
    await _add_monitor(db, due_delta_min=-5)
    await _add_monitor(db, due_delta_min=-4)
    n = await rm.run_due_once()
    assert n == 1  # only one LLM-heavy check launched this tick; the other waits
    assert len(_capture_launches) == 1


async def test_stale_running_check_is_reclaimed(db, _capture_launches):
    settings = get_settings()
    stale = _now() - timedelta(minutes=settings.monitor_stale_running_minutes + 10)
    m = await _add_monitor(db, due_delta_min=-5, last_status="running", last_checked_at=stale)
    # A check stuck "running" past the stale window is eligible again (spec §34).
    assert await rm.run_due_once() == 1
    assert _capture_launches == [m.id]


async def test_recent_running_check_is_not_reclaimed(db, _capture_launches):
    recent = _now() - timedelta(minutes=1)
    await _add_monitor(db, due_delta_min=-5, last_status="running", last_checked_at=recent)
    assert await rm.run_due_once() == 0  # a genuinely in-flight check is left alone


async def test_backoff_grows_and_is_capped(db):
    settings = get_settings()
    m = await _add_monitor(db, interval=1440)
    m.consecutive_failures = 1
    d1 = rm._next_after_failure(m)
    m.consecutive_failures = 3
    d3 = rm._next_after_failure(m)
    # More failures → later retry (exponential), but never beyond the cap.
    assert d3 > d1
    cap = _now() + timedelta(minutes=settings.monitor_backoff_cap_minutes + 1)
    m.consecutive_failures = 50
    assert rm._next_after_failure(m) <= cap


async def test_monitor_survives_restart(db, _capture_launches):
    """A persisted monitor is picked up by a fresh poller pass (spec §34 restart-safe)."""
    m = await _add_monitor(db, due_delta_min=-5)
    # Simulate a process restart: clear in-memory run state, keep the DB row.
    rm._running.clear()
    rm._tasks.clear()
    assert await rm.run_due_once() == 1
    assert _capture_launches == [m.id]
