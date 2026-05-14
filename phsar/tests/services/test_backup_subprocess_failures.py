"""Failure-branch tests for backup_service that don't shell out to real
pg_dump / pg_restore / psql. They inject a fake subprocess runner via the
seam in app.services._pg_subprocess so we can exercise non-zero returncodes,
timeouts, and corrupt-archive stderr without an actual Postgres install."""

import asyncio
from pathlib import Path

import pytest

from app.core.config import settings
from app.exceptions import BackupIntegrityError, BackupRestoreError
from app.schemas.backup_schema import BackupIntegrity, BackupSource
from app.services import _pg_subprocess, backup_service


class _FakeProcess:
    """Stand-in for asyncio.subprocess.Process. Supports the subset of methods
    run_capture actually calls: communicate / kill / wait / returncode."""

    def __init__(self, returncode: int, stdout: bytes = b"", stderr: bytes = b"", hang: bool = False):
        self._returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self.killed = False

    @property
    def returncode(self) -> int:
        return self._returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            # Raise directly so the test exercises run_capture's kill/wait
            # path without burning real wall-clock time on asyncio.wait_for.
            raise asyncio.TimeoutError()
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self._returncode


def _patch_runner(monkeypatch, process: _FakeProcess) -> None:
    """Replace the module-level default runner so every run_capture call in
    this test sees the same canned process. Tests that need different fakes
    per call swap the runner mid-test."""
    async def _fake_runner(*_args, **_kwargs):
        return process
    monkeypatch.setattr(_pg_subprocess, "_default_runner", _fake_runner)


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path))
    return tmp_path


async def test_pg_dump_nonzero_raises_integrity_and_unlinks_partial(backup_dir, monkeypatch):
    """pg_dump exits non-zero → BackupIntegrityError surfaces stderr, the
    .partial file is removed, and no final dump is left behind."""
    _patch_runner(monkeypatch, _FakeProcess(returncode=1, stderr=b"connection refused"))

    with pytest.raises(BackupIntegrityError) as excinfo:
        await backup_service.create_backup(source=BackupSource.manual)

    assert "connection refused" in str(excinfo.value)
    assert list(backup_dir.glob("*.dump")) == []
    assert list(backup_dir.glob("*.partial")) == []


async def test_pg_restore_timeout_raises_descriptive_error(monkeypatch):
    """A hanging pg_restore gets killed by the timeout and produces an error
    message that points the admin at the pre-restore snapshot recovery path."""
    fake = _FakeProcess(returncode=0, hang=True)
    _patch_runner(monkeypatch, fake)

    with pytest.raises(BackupRestoreError) as excinfo:
        await backup_service._run_pg_restore(Path("/tmp/fake.dump"), "fake.dump")

    assert "timeout" in str(excinfo.value).lower()
    assert "pre-restore snapshot" in str(excinfo.value)
    assert fake.killed is True


async def test_pg_restore_nonzero_raises_with_stderr(monkeypatch):
    """pg_restore exits non-zero (e.g. dump format mismatch) → BackupRestoreError
    surfaces the stderr tail so the admin sees the real Postgres complaint."""
    _patch_runner(monkeypatch, _FakeProcess(returncode=1, stderr=b"unsupported version"))

    with pytest.raises(BackupRestoreError) as excinfo:
        await backup_service._run_pg_restore(Path("/tmp/fake.dump"), "fake.dump")

    assert "unsupported version" in str(excinfo.value)


async def test_check_integrity_returns_corrupt_on_nonzero(monkeypatch):
    """pg_restore --list exits non-zero → integrity check classifies as corrupt."""
    _patch_runner(monkeypatch, _FakeProcess(returncode=1, stderr=b"input file is too short"))

    result = await backup_service._check_integrity(Path("/tmp/fake.dump"))
    assert result is BackupIntegrity.corrupt


async def test_check_integrity_returns_ok_on_zero(monkeypatch):
    """Zero returncode → integrity OK."""
    _patch_runner(monkeypatch, _FakeProcess(returncode=0))

    result = await backup_service._check_integrity(Path("/tmp/fake.dump"))
    assert result is BackupIntegrity.ok


async def test_terminate_other_sessions_swallows_psql_failure(monkeypatch, caplog):
    """Fire-and-forget: a non-zero psql does NOT raise; it logs a warning so
    the postmortem on a 'pg_restore hung on locks' is traceable."""
    _patch_runner(monkeypatch, _FakeProcess(returncode=2, stderr=b"psql: error: connection refused"))

    with caplog.at_level("WARNING"):
        await backup_service._terminate_other_sessions()

    assert any("Terminate-other-sessions" in r.message for r in caplog.records)
