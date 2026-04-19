"""Tests for backup_service.

These exercise the real pg_dump / pg_restore subprocesses against the test
database. Each test gets its own tmp backup directory via monkeypatch on
settings.BACKUP_DIR, so no state leaks out to the real /backups volume.
"""

import io

import pytest
from fastapi import UploadFile

from app.core.config import settings
from app.exceptions import DuplicateBackupError
from app.schemas.backup_schema import BackupSource
from app.services import backup_service


@pytest.fixture
def backup_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_DIR", str(tmp_path))
    return tmp_path


async def test_content_hash_stable_across_invocations(backup_dir):
    """Hash must be stable across pg_restore runs for dedupe to work — the
    \\restrict token is randomized per run, so without normalization this
    test would fail."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    dump_path = backup_dir / first.filename
    h1 = await backup_service._compute_content_hash(dump_path)
    h2 = await backup_service._compute_content_hash(dump_path)
    assert h1 == h2
    assert h1 == first.content_hash


async def test_manual_backup_dedupes_with_error(backup_dir):
    """Admin clicked Create twice with no DB change between — second call
    raises DuplicateBackupError pointing at the first dump."""
    first = await backup_service.create_backup(source=BackupSource.manual)
    with pytest.raises(DuplicateBackupError) as excinfo:
        await backup_service.create_backup(source=BackupSource.manual)
    assert first.filename in str(excinfo.value)

    dumps = list(backup_dir.glob("phsar-*.dump"))
    assert [p.name for p in dumps] == [first.filename]


async def test_cron_backup_dedupes_silently(backup_dir):
    """Scheduled cron calls return the existing dump instead of raising, so
    unchanged DBs don't accumulate identical scheduled snapshots."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    second = await backup_service.create_backup(source=BackupSource.cron)
    assert second.filename == first.filename

    dumps = list(backup_dir.glob("phsar-*.dump"))
    assert len(dumps) == 1


async def test_pre_restore_backup_dedupes_silently(backup_dir):
    """pre_restore snapshots are retention-exempt; silent dedupe prevents
    them from piling up on repeat restores of the same-state dump."""
    first = await backup_service.create_backup(source=BackupSource.manual)
    second = await backup_service.create_backup(source=BackupSource.pre_restore)
    assert second.filename == first.filename

    dumps = list(backup_dir.glob("phsar-*.dump"))
    assert len(dumps) == 1


async def test_upload_of_same_content_raises(backup_dir):
    """Round-trip (create → download bytes → upload bytes) must dedupe.
    This is the specific flow that exposed the \\restrict-token bug."""
    first = await backup_service.create_backup(source=BackupSource.manual)
    dump_bytes = (backup_dir / first.filename).read_bytes()

    upload = UploadFile(
        filename="phsar-downloaded.dump",
        file=io.BytesIO(dump_bytes),
    )
    with pytest.raises(DuplicateBackupError) as excinfo:
        await backup_service.save_uploaded_backup(upload)
    assert first.filename in str(excinfo.value)


async def test_dedupe_match_repoints_current_db_on_create(backup_dir):
    """A dedupe hit from create_backup sets the current-DB pointer to the
    existing dump, so the UI's 'Current' badge follows DB state — even if
    the matching dump is older than any other backup."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() is None

    await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    items = await backup_service.list_backups()
    assert len(items) == 1
    assert items[0].is_current is True


async def test_dedupe_match_repoints_current_db_on_upload(backup_dir):
    """Same pointer-update behavior on the upload path: if an uploaded dump
    matches an existing one, the existing dump gets the Current badge."""
    first = await backup_service.create_backup(source=BackupSource.manual)
    dump_bytes = (backup_dir / first.filename).read_bytes()

    assert backup_service._read_current_db_filename() is None

    upload = UploadFile(
        filename="phsar-downloaded.dump",
        file=io.BytesIO(dump_bytes),
    )
    with pytest.raises(DuplicateBackupError):
        await backup_service.save_uploaded_backup(upload)

    assert backup_service._read_current_db_filename() == first.filename


async def test_delete_clears_current_db_pointer(backup_dir):
    """Deleting the dump that the pointer references must drop the pointer
    file too — otherwise list_backups would badge a nonexistent dump."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    # Force pointer to be set via a dedupe match.
    await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    await backup_service.delete_backup(first.filename)
    assert backup_service._read_current_db_filename() is None


async def test_list_backups_unbadged_when_no_match(backup_dir):
    """Fresh backup with no restore and no dedupe match: no Current badge."""
    await backup_service.create_backup(source=BackupSource.manual)
    items = await backup_service.list_backups()
    assert len(items) == 1
    assert items[0].is_current is False
