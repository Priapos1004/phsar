"""Tests for ProgressReporter throttle behavior.

The reporter opens a fresh session per persisted update; without throttling
a tight BFS loop would open hundreds of sessions per second. These tests
exercise the throttle without touching the DB by patching the persistence
helper to count calls.
"""

import asyncio

import pytest

from app.services import progress_reporter as pr_module
from app.services.progress_reporter import ProgressReporter


@pytest.fixture(autouse=True)
def _patch_persistence(monkeypatch):
    """Replace the throttle's persistence call with an async no-op counter."""
    calls: list[dict] = []

    async def _fake_session_maker():
        class _FakeCtx:
            async def __aenter__(self_inner):
                return self_inner
            async def __aexit__(self_inner, *_):
                return None
            async def commit(self_inner):
                return None
        return _FakeCtx()

    # Sidestep async_session_maker entirely by stubbing the dao methods that
    # ProgressReporter calls. Easier than building a fake session.
    async def fake_get_by_id(_session, job_id):
        return object()

    async def fake_mark_progress(_session, _job, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(pr_module.job_dao, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(pr_module.job_dao, "mark_progress", fake_mark_progress)

    class _FakeSession:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return None
        async def commit(self):
            return None

    def fake_session_maker():
        return _FakeSession()

    monkeypatch.setattr(pr_module, "async_session_maker", fake_session_maker)
    return calls


@pytest.mark.asyncio
async def test_throttle_drops_rapid_updates(_patch_persistence):
    """Two updates inside the throttle window — only the first is persisted."""
    reporter = ProgressReporter(job_id=1, min_interval_s=10.0)

    await reporter.update(items_done=1)
    await reporter.update(items_done=2)

    assert len(_patch_persistence) == 1
    assert _patch_persistence[0]["items_done"] == 1


@pytest.mark.asyncio
async def test_force_bypasses_throttle(_patch_persistence):
    """force=True writes immediately even within the throttle window — used
    for stage transitions like Fetching → Saving → Done."""
    reporter = ProgressReporter(job_id=1, min_interval_s=10.0)

    await reporter.update(items_done=1)
    await reporter.update(stage="Saving", force=True)

    assert len(_patch_persistence) == 2
    assert _patch_persistence[1]["stage"] == "Saving"


@pytest.mark.asyncio
async def test_update_after_throttle_window(_patch_persistence):
    """Once min_interval has elapsed, the next update persists."""
    reporter = ProgressReporter(job_id=1, min_interval_s=0.05)

    await reporter.update(items_done=1)
    await asyncio.sleep(0.07)
    await reporter.update(items_done=2)

    assert len(_patch_persistence) == 2
    assert _patch_persistence[1]["items_done"] == 2
