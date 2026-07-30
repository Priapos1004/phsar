"""backup_dispatcher tests.

The dispatcher wraps backup_service.create_backup, surfaces content-hash
dedupe as a success outcome (`deduped_against` on result_summary), and
applies retention after every successful job (manual + cron alike).

Happy-path and dedupe tests call the dispatcher directly with a FakeJob
because they only assert on the returned summary. The failure-mode tests
run through the full JobWorker loop so we also pin the worker's
classify_error → error_category contract — that's the surface the bell
actually reads.

Subprocess failures use the same _pg_subprocess._default_runner seam that
test_backup_subprocess_failures.py uses, so no real Postgres install is
required.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import settings
from app.core.db import async_session_maker
from app.daos.job_dao import JobDAO
from app.exceptions import BackupDiskSpaceError
from app.models.job import Job, JobKind, JobStatus
from app.schemas.backup_schema import (
    BackupIntegrity,
    BackupListResponse,
    BackupMetadata,
    BackupSource,
    BackupStatus,
)
from app.services import _pg_subprocess, backup_dispatcher, backup_service
from app.services.job_worker import JobWorker

dao = JobDAO()


class _FakeProcess:
    """Mirrors the _FakeProcess in test_backup_subprocess_failures.py
    closely enough to drive `run_capture` without a real Postgres."""

    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    @property
    def returncode(self) -> int:
        return self._returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        return self._returncode


class _NoopProgressReporter:
    """Match the pattern in test_seasonal_sweep — ProgressReporter opens
    its own short-lived sessions which would pollute the test DB; the
    dispatcher's behavior doesn't depend on whether updates land."""

    def __init__(self, *_args, **_kwargs):
        pass

    async def update(self, *_args, **_kwargs):
        return None


def _patch_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.backup_dispatcher.ProgressReporter", _NoopProgressReporter,
    )


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path))
    return tmp_path


async def _enqueue_backup_job(payload: dict) -> int:
    async with async_session_maker() as s:
        job = Job(kind=JobKind.backup, status=JobStatus.queued, payload=payload)
        s.add(job)
        await s.flush()
        await s.commit()
        return job.id


async def _get_job(job_id: int) -> Job | None:
    async with async_session_maker() as s:
        return await dao.get_by_id(s, job_id)


def _fake_job(payload: dict, job_id: int = 12345):
    return type("FakeJob", (), {"id": job_id, "payload": payload})()


# ---------------------------------------------------------------------------
# Dispatcher unit tests — call backup_dispatcher directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backup_dispatcher_rejects_payload_missing_source(backup_dir, monkeypatch):
    """The payload is JSONB so the router could in principle drift from the
    dispatcher's expectations. BackupJobPayload's pydantic validation
    surfaces drift here as a clean ValidationError that JobWorker stamps as
    the failure reason, instead of an opaque KeyError deeper in dispatch."""
    _patch_progress(monkeypatch)

    async with async_session_maker() as session:
        with pytest.raises(ValidationError):
            await backup_dispatcher.backup_dispatcher(session, _fake_job({}))


@pytest.mark.asyncio
async def test_backup_dispatcher_rejects_payload_with_unknown_field(backup_dir, monkeypatch):
    """BackupJobPayload sets `extra='forbid'` so a typo in the router's
    payload construction (e.g. `tag` instead of `label`) surfaces at job
    pickup instead of silently dropping the field."""
    _patch_progress(monkeypatch)

    async with async_session_maker() as session:
        with pytest.raises(ValidationError):
            await backup_dispatcher.backup_dispatcher(
                session, _fake_job({"source": "manual", "tag": "oops"}),
            )


@pytest.mark.asyncio
async def test_backup_dispatcher_creates_dump(backup_dir, monkeypatch):
    """Happy path: a manual backup runs pg_dump, lands a single .dump in
    BACKUP_DIR, and returns the structured summary the bell consumes."""
    _patch_progress(monkeypatch)

    async with async_session_maker() as session:
        summary = await backup_dispatcher.backup_dispatcher(
            session, _fake_job({"source": "manual"}),
        )

    assert summary["filename"].startswith("phsar-")
    assert summary["filename"].endswith(".dump")
    assert summary["size_bytes"] > 0
    assert summary["integrity"] == "ok"
    assert summary["source"] == "manual"
    assert summary["deduped_against"] is None

    dumps = list(backup_dir.glob("phsar-*.dump"))
    assert len(dumps) == 1
    assert dumps[0].name == summary["filename"]


@pytest.mark.asyncio
async def test_backup_dispatcher_surfaces_dedupe_as_success(backup_dir, monkeypatch):
    """Two manual creates with no DB change between: synchronously the
    second would raise DuplicateBackupError (409). The dispatcher
    converts that into a success outcome with `deduped_against` so the
    bell can render 'Re-confirmed existing dump' instead of a hard fail."""
    _patch_progress(monkeypatch)

    async with async_session_maker() as session:
        first = await backup_dispatcher.backup_dispatcher(
            session, _fake_job({"source": "manual"}, job_id=1001),
        )
        second = await backup_dispatcher.backup_dispatcher(
            session, _fake_job({"source": "manual"}, job_id=1002),
        )

    assert first["deduped_against"] is None
    assert second["deduped_against"] == first["filename"]
    assert second["filename"] == first["filename"]

    dumps = list(backup_dir.glob("phsar-*.dump"))
    assert len(dumps) == 1


@pytest.mark.asyncio
async def test_backup_dispatcher_cron_applies_retention(backup_dir, monkeypatch):
    """Cron-source jobs apply retention after the dump, enforcing the
    14-recent + 8-Sunday + 1-known-good contract."""
    _patch_progress(monkeypatch)

    retention_calls: list[int] = []

    async def fake_retention():
        retention_calls.append(1)
        return []

    monkeypatch.setattr(backup_service, "apply_retention", fake_retention)

    async with async_session_maker() as session:
        await backup_dispatcher.backup_dispatcher(
            session, _fake_job({"source": "cron"}, job_id=2001),
        )
    assert retention_calls == [1]


@pytest.mark.asyncio
async def test_backup_dispatcher_manual_applies_retention(backup_dir, monkeypatch):
    """Manual jobs also apply retention. Without this, manual creates
    pile up indefinitely on installs where cron is disabled (empty
    `JOBS_CRON_TOKEN`) or rarely fires, since the cron path was the
    only one historically wired to retention. Same shared pool — manual
    and cron compete for the same slots in the 14-recent + 8-Sunday + 1
    keep budget."""
    _patch_progress(monkeypatch)

    retention_calls: list[int] = []

    async def fake_retention():
        retention_calls.append(1)
        return []

    monkeypatch.setattr(backup_service, "apply_retention", fake_retention)

    async with async_session_maker() as session:
        await backup_dispatcher.backup_dispatcher(
            session, _fake_job({"source": "manual"}, job_id=2002),
        )
    assert retention_calls == [1]


@pytest.mark.asyncio
async def test_backup_dispatcher_propagates_disk_full(backup_dir, monkeypatch):
    """A disk-space failure must propagate so the worker stamps
    error_category=backup_disk_full on result_summary. The worker leg of
    this contract is covered by the integration test below; this one
    pins the raise side."""
    _patch_progress(monkeypatch)

    async def fake_create(**_kwargs):
        raise BackupDiskSpaceError(free_bytes=1024, required_bytes=500 * 1024 * 1024)

    monkeypatch.setattr(backup_service, "create_backup", fake_create)

    async with async_session_maker() as session:
        with pytest.raises(BackupDiskSpaceError):
            await backup_dispatcher.backup_dispatcher(
                session, _fake_job({"source": "manual"}, job_id=3001),
            )


# ---------------------------------------------------------------------------
# Worker-integration tests — verify the error_category contract on real
# job rows. Mirrors test_job_worker's tracked_jobs / _enqueue / dispatch_one
# pattern.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_classifies_disk_full_as_backup_disk_full(
    backup_dir, tracked_jobs, monkeypatch,
):
    """End-to-end: the dispatcher's BackupDiskSpaceError surfaces on
    result_summary.error_category so the bell can render an actionable
    'Free disk space' hint instead of the raw 'Insufficient disk space'
    detail line."""
    _patch_progress(monkeypatch)

    async def fake_create(**_kwargs):
        raise BackupDiskSpaceError(free_bytes=1024, required_bytes=500 * 1024 * 1024)

    monkeypatch.setattr(backup_service, "create_backup", fake_create)

    worker = JobWorker()
    worker.register_dispatcher(JobKind.backup, backup_dispatcher.backup_dispatcher)

    job_id = await _enqueue_backup_job({"source": "manual"})
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get_job(job_id)
    assert refreshed.status is JobStatus.failed
    assert refreshed.result_summary is not None
    assert refreshed.result_summary.get("error_category") == "backup_disk_full"
    # Disk-full is fixable (admin frees space then retries) — leave the
    # retry button enabled instead of locking the user out.
    assert refreshed.result_summary.get("retryable") is True


@pytest.mark.asyncio
async def test_worker_classifies_pg_dump_failure_as_backup_corrupt(
    backup_dir, tracked_jobs, monkeypatch,
):
    """A non-zero pg_dump exit raises BackupIntegrityError inside
    backup_service.create_backup. The worker tags it `backup_corrupt`
    so the bell shows 'Backup archive corrupt' copy with the stderr
    tail available in error_message."""
    _patch_progress(monkeypatch)

    async def fake_runner(*_args, **_kwargs):
        return _FakeProcess(returncode=1, stderr=b"pg_dump: error: connection refused")

    monkeypatch.setattr(_pg_subprocess, "_default_runner", fake_runner)

    worker = JobWorker()
    worker.register_dispatcher(JobKind.backup, backup_dispatcher.backup_dispatcher)

    job_id = await _enqueue_backup_job({"source": "manual"})
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get_job(job_id)
    assert refreshed.status is JobStatus.failed
    assert refreshed.result_summary is not None
    assert refreshed.result_summary.get("error_category") == "backup_corrupt"
    assert refreshed.result_summary.get("retryable") is True
    assert "connection refused" in (refreshed.error_message or "")


@pytest.mark.asyncio
async def test_worker_does_not_bracket_maintenance_for_backup(
    tracked_jobs, monkeypatch,
):
    """pg_dump runs on an MVCC snapshot — there's no reason to block
    user writes during a dump window. The worker's _MAINTENANCE_KINDS
    must NOT include `backup`, or every backup would 503 every
    concurrent user request for the duration of the dump."""

    from app.core import maintenance

    _patch_progress(monkeypatch)

    captured_active: list[bool] = []

    async def fake_create(*, source, label=None):
        # Snapshot the maintenance flag at dispatch time — what the test
        # actually cares about. Return a synthetic metadata so the
        # dispatcher's summary build doesn't need a real pg_dump.
        captured_active.append(maintenance.is_maintenance_active())
        return BackupMetadata(
            filename="phsar-19700101-000000.dump",
            size_bytes=1024,
            created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
            integrity=BackupIntegrity.ok,
            source=source,
        )

    monkeypatch.setattr(backup_service, "create_backup", fake_create)

    worker = JobWorker()
    worker.register_dispatcher(JobKind.backup, backup_dispatcher.backup_dispatcher)

    job_id = await _enqueue_backup_job({"source": "manual"})
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    # Maintenance flag was OFF during dispatch — backups don't bracket.
    assert captured_active == [False]
    refreshed = await _get_job(job_id)
    assert refreshed.status is JobStatus.succeeded


# ---------------------------------------------------------------------------
# Startup self-heal (`backup_service.ensure_up_to_date_backup`)
#
# The predicate, not the dump: `list_backups` is stubbed so these stay fast and
# don't shell out to pg_dump. Rows are committed, so `tracked_jobs` cleans up.
# ---------------------------------------------------------------------------


def _listed(status: BackupStatus, **over) -> BackupMetadata:
    """A minimal listing row. `status` is the server-derived composite the
    self-heal reads — the same field the Backups card renders."""
    return BackupMetadata(
        filename=over.pop("filename", "phsar-19700101-000000-cron.dump"),
        size_bytes=1,
        created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        integrity=over.pop("integrity", BackupIntegrity.ok),
        source=over.pop("source", BackupSource.cron),
        status=status,
        **over,
    )


@pytest.fixture
def stub_listing(monkeypatch):
    """Install a fake listing envelope and silence the worker ping.

    Patches `list_backups_with_revision` — the envelope IS what the self-heal reads,
    so both halves of its decision come from one revision read.
    """
    def _install(*rows: BackupMetadata, db_revision: str | None = "new"):
        async def _fake_list():
            return BackupListResponse(db_revision=db_revision, backups=list(rows))

        monkeypatch.setattr(backup_service, "list_backups_with_revision", _fake_list)
        monkeypatch.setattr(backup_service.job_worker, "notify", lambda: None)

    return _install


async def _count_queued_backups() -> int:
    async with async_session_maker() as s:
        return await dao.count_active_by_kind(s, JobKind.backup)


async def _latest_queued_backup() -> Job:
    async with async_session_maker() as s:
        return (await s.execute(
            select(Job)
            .where(Job.kind == JobKind.backup, Job.status == JobStatus.queued)
            .order_by(Job.id.desc())
            .limit(1)
        )).scalar_one()


@pytest.mark.asyncio
async def test_startup_skips_when_a_restorable_backup_exists(stub_listing):
    stub_listing(_listed(BackupStatus.ok))
    before = await _count_queued_backups()
    await backup_service.ensure_up_to_date_backup()
    assert await _count_queued_backups() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [BackupStatus.outdated, BackupStatus.unknown, BackupStatus.corrupt],
    ids=["schema-stale", "schema-unverifiable", "corrupt-file"],
)
async def test_startup_enqueues_when_nothing_on_disk_is_restorable(
    status, tracked_jobs, stub_listing,
):
    """Only `ok` counts. `unknown` is the one worth spelling out: a dump we can't
    vouch for must not satisfy the predicate, and the card agrees with this now
    because both read the same server-derived `status`."""
    stub_listing(_listed(status, alembic_revision="old"))
    before = await _count_queued_backups()

    await backup_service.ensure_up_to_date_backup()

    assert await _count_queued_backups() == before + 1
    job = await _latest_queued_backup()
    tracked_jobs.append(job.id)
    assert job.requested_by_user_id is None  # system job — invisible to every bell
    assert job.payload == {"source": BackupSource.cron.value}


@pytest.mark.asyncio
async def test_startup_skips_when_the_live_revision_is_unreadable(stub_listing):
    """`status` is a comparison against the live revision, so with it unreadable no
    dump can ever be `ok` — including one taken right now. Enqueueing on a verdict
    that can't be computed re-fires on every restart and evicts real archival history,
    so the unreadable case must be a no-op even though nothing looks restorable."""
    stub_listing(_listed(BackupStatus.unknown), db_revision=None)
    before = await _count_queued_backups()
    await backup_service.ensure_up_to_date_backup()
    assert await _count_queued_backups() == before


@pytest.mark.asyncio
async def test_startup_does_not_stack_a_second_backup(tracked_jobs, stub_listing):
    """A restart landing while a dump is still queued must not enqueue another —
    the listing can't see an in-flight job, so the kind-scoped active count is
    what stops the pile-up across rapid restarts."""
    stub_listing(_listed(BackupStatus.outdated))
    tracked_jobs.append(await _enqueue_backup_job({"source": "cron"}))
    before = await _count_queued_backups()
    await backup_service.ensure_up_to_date_backup()
    assert await _count_queued_backups() == before
