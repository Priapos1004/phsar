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


async def test_first_dump_claims_current_on_fresh_install(backup_dir):
    """On a fresh VM with no prior Current pointer, the first successful
    create_backup marks itself current — otherwise the badge would stay
    empty until the admin manually triggered a redundant dedupe-confirm."""
    assert backup_service._read_current_db_filename() is None

    first = await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename
    assert first.is_current is True

    items = await backup_service.list_backups()
    assert len(items) == 1
    assert items[0].is_current is True


async def test_dedupe_match_repoints_current_db_on_create(backup_dir):
    """A dedupe hit from create_backup keeps the Current pointer on the
    matching existing dump, so the UI's 'Current' badge follows DB state —
    even if the matching dump is older than any other backup."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    items = await backup_service.list_backups()
    assert len(items) == 1
    assert items[0].is_current is True


async def test_upload_dedupe_does_not_move_current_pointer(backup_dir):
    """An upload that matches an existing dump byte-for-byte must NOT touch
    the Current pointer — uploaded bytes are external (could be any
    historical or third-party dump) and we have no way to verify they
    represent the live DB. Only live-capturing triggers (create/restore)
    are allowed to move Current."""
    first = await backup_service.create_backup(source=BackupSource.manual)
    dump_bytes = (backup_dir / first.filename).read_bytes()
    pointer_before = backup_service._read_current_db_filename()
    assert pointer_before == first.filename

    upload = UploadFile(
        filename="phsar-downloaded.dump",
        file=io.BytesIO(dump_bytes),
    )
    with pytest.raises(DuplicateBackupError):
        await backup_service.save_uploaded_backup(upload)

    assert backup_service._read_current_db_filename() == pointer_before


async def test_delete_clears_current_db_pointer(backup_dir):
    """Deleting the dump that the pointer references must drop the pointer
    file too — otherwise list_backups would badge a nonexistent dump."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    await backup_service.delete_backup(first.filename)
    assert backup_service._read_current_db_filename() is None


async def test_unique_create_moves_current_to_new_dump(backup_dir, monkeypatch):
    """A successful manual/cron create captures live DB state via pg_dump,
    so the resulting dump IS the live state by construction. Current must
    move to it — staying on an older dump leaves the badge advertising a
    file that no longer matches live, defeating the whole point of the
    badge for the most common operation."""
    first = await backup_service.create_backup(source=BackupSource.cron)
    assert backup_service._read_current_db_filename() == first.filename

    # Force the next dump to hash differently so it exercises the
    # "unique create with pointer already set" branch (the rollback-pattern
    # blocks real DB mutations between dumps).
    real_hash = backup_service._compute_content_hash

    async def _perturbed(path):
        return (await real_hash(path)) + "-x"

    monkeypatch.setattr(backup_service, "_compute_content_hash", _perturbed)
    second = await backup_service.create_backup(source=BackupSource.cron)

    # Live state was just captured into `second`; Current must follow.
    assert second.is_current is True
    assert backup_service._read_current_db_filename() == second.filename


async def test_upload_unique_does_not_claim_current_on_fresh_install(backup_dir):
    """On a fresh install with no Current pointer yet, an upload must NOT
    bootstrap Current — uploads bring in external state and we have no way
    to validate that the uploaded bytes match the live DB. The admin must
    explicitly create a dump (manual or cron) to establish a validated
    baseline. The badge stays empty in the meantime, which is the truthful
    state ('we haven't confirmed any dump matches live yet')."""
    assert backup_service._read_current_db_filename() is None

    # Capture a real pg_dump archive's bytes so the upload passes the
    # integrity check (which runs pg_restore --list on the bytes).
    seed = await backup_service.create_backup(source=BackupSource.cron)
    dump_bytes = (backup_dir / seed.filename).read_bytes()
    await backup_service.delete_backup(seed.filename)
    assert backup_service._read_current_db_filename() is None

    upload = UploadFile(
        filename="phsar-external.dump",
        file=io.BytesIO(dump_bytes),
    )
    uploaded = await backup_service.save_uploaded_backup(upload)
    assert uploaded.is_current is False
    assert backup_service._read_current_db_filename() is None


# 3x3 matrix: trigger A on a fresh dir → DB mutates (simulated via the
# unique-hash fixture) → trigger B. Asserts how Current moves across the
# nine combinations. Triggers that capture live (manual/cron) must move
# Current forward; uploads must never touch the pointer.
_TRIGGERS = ("manual", "cron", "upload")
_LIVE_CAPTURE = frozenset({"manual", "cron"})


async def _run_trigger(name: str, real_dump_bytes: bytes, step: str):
    """Run one trigger. `step` ("a"/"b") is folded into the label/filename
    so back-to-back manual+manual or cron+cron creates inside the same
    wall-clock second produce distinct filenames; without it `_build_filename`
    derives only second-resolution timestamps and the second `os.rename`
    silently clobbers the first dump on disk."""
    if name == "manual":
        return await backup_service.create_backup(source=BackupSource.manual, label=step)
    if name == "cron":
        return await backup_service.create_backup(source=BackupSource.cron, label=step)
    if name == "upload":
        upload = UploadFile(
            filename=f"phsar-upload-{name}-{step}.dump",
            file=io.BytesIO(real_dump_bytes),
        )
        return await backup_service.save_uploaded_backup(upload)
    raise ValueError(f"unknown trigger: {name}")


@pytest.fixture
def unique_hashes(monkeypatch):
    """Force every dump to produce a unique content hash. The rollback-style
    fixture blocks real DB mutations between dumps, so without this every
    pair would dedupe — masking the unique-create branches we're testing."""
    real = backup_service._compute_content_hash
    counter = {"i": 0}

    async def _perturbed(path):
        h = await real(path)
        counter["i"] += 1
        return f"{h}-tag{counter['i']}"

    monkeypatch.setattr(backup_service, "_compute_content_hash", _perturbed)


async def test_create_dedupe_after_restore_moves_current_to_matched(
    backup_dir, monkeypatch,
):
    """Post-restore state: restore set Current to an older dump (A), while a
    newer non-Current dump (B) also exists on disk. A subsequent create
    that pg_dumps live and finds the bytes match B (e.g. another roundtrip
    brought live back to B's state) must move Current to B — leaving it
    on A would advertise a dump that no longer matches live, which is
    exactly the bug the badge is meant to prevent.

    We simulate post-restore state by calling `_mark_current_db_restored`
    directly (running real `restore_backup` would clobber the test DB).
    Hash perturbation is monkeypatched twice: first to give A and B unique
    hashes so neither dedupes against the other, then to force the third
    create to compute B's exact hash so it dedupes against B."""
    counter = {"i": 0}

    async def _unique_per_call(_path):
        counter["i"] += 1
        return f"hash-{counter['i']}"

    monkeypatch.setattr(backup_service, "_compute_content_hash", _unique_per_call)

    # Labels disambiguate the filenames — `_build_filename` derives the
    # name from the per-second timestamp, so two creates inside the same
    # second would otherwise collide and the second rename would clobber
    # the first dump on disk.
    a = await backup_service.create_backup(source=BackupSource.cron, label="a")
    b = await backup_service.create_backup(source=BackupSource.cron, label="b")
    assert a.filename != b.filename
    # Most recent create was B, so the pointer naturally sits on B.
    assert backup_service._read_current_db_filename() == b.filename

    # Simulate post-restore: pointer back on the older A.
    backup_service._mark_current_db_restored(a.filename)
    assert backup_service._read_current_db_filename() == a.filename

    # Force the next create to hash-collide with B (live state happens to
    # match what B captured).
    async def _collide_with_b(_path):
        return b.content_hash

    monkeypatch.setattr(backup_service, "_compute_content_hash", _collide_with_b)

    third = await backup_service.create_backup(source=BackupSource.cron, label="third")

    # The dedupe-create matched B → live == B's content → Current → B,
    # not A (which now represents a stale state pg_dump just walked away
    # from).
    assert third.filename == b.filename
    assert third.is_current is True
    assert backup_service._read_current_db_filename() == b.filename


async def test_upload_dedupe_after_restore_does_not_move_current(
    backup_dir, monkeypatch,
):
    """Same post-restore setup, different second action: admin uploads
    bytes that happen to match a non-Current dump (B). Current must NOT
    move to B — uploaded bytes are external and we have no way to verify
    they represent live DB state. The admin could be uploading any
    historical or third-party dump."""
    counter = {"i": 0}

    async def _unique_per_call(_path):
        counter["i"] += 1
        return f"hash-{counter['i']}"

    monkeypatch.setattr(backup_service, "_compute_content_hash", _unique_per_call)

    a = await backup_service.create_backup(source=BackupSource.cron, label="a")
    b = await backup_service.create_backup(source=BackupSource.cron, label="b")
    b_bytes = (backup_dir / b.filename).read_bytes()

    backup_service._mark_current_db_restored(a.filename)
    assert backup_service._read_current_db_filename() == a.filename

    # Force the upload-finalize hash to collide with B (the uploaded bytes
    # match B byte-for-byte; the real hasher would arrive at the same
    # result, this just keeps the test independent of pg_restore output).
    async def _collide_with_b(_path):
        return b.content_hash

    monkeypatch.setattr(backup_service, "_compute_content_hash", _collide_with_b)

    upload = UploadFile(
        filename="phsar-from-elsewhere.dump",
        file=io.BytesIO(b_bytes),
    )
    with pytest.raises(DuplicateBackupError):
        await backup_service.save_uploaded_backup(upload)

    # Upload dedupe must not touch Current; pointer stays on A.
    assert backup_service._read_current_db_filename() == a.filename


@pytest.mark.parametrize(
    "trigger_a,trigger_b",
    [(a, b) for a in _TRIGGERS for b in _TRIGGERS],
)
async def test_current_pointer_matrix(
    backup_dir, unique_hashes, trigger_a, trigger_b,
):
    """3x3 matrix over the three creation triggers, asserting how the
    Current pointer responds to (A, simulated-DB-change, B). Each cell
    documents the correct semantics: pg_dump captures live (manual/cron
    move the pointer); upload brings in external bytes (never moves)."""
    # Uploads need real pg_dump bytes so the integrity check passes; capture
    # them in a temporary sibling dir and discard so the per-test BACKUP_DIR
    # starts empty.
    seed = await backup_service.create_backup(source=BackupSource.cron)
    real_dump_bytes = (backup_dir / seed.filename).read_bytes()
    await backup_service.delete_backup(seed.filename)
    assert backup_service._read_current_db_filename() is None

    # Step 1 — trigger A on a fresh dir.
    dump_a = await _run_trigger(trigger_a, real_dump_bytes, step="a")
    pointer_after_a = backup_service._read_current_db_filename()

    if trigger_a in _LIVE_CAPTURE:
        assert pointer_after_a == dump_a.filename, (
            f"trigger A ({trigger_a}) should have set Current to its own dump"
        )
        assert dump_a.is_current is True
    else:  # upload
        assert pointer_after_a is None, (
            "upload on fresh install must not bootstrap Current"
        )
        assert dump_a.is_current is False

    # Step 2 — DB state mutation is simulated by the unique-hash fixture
    # (every subsequent dump looks unique to the dedupe check).

    # Step 3 — trigger B.
    dump_b = await _run_trigger(trigger_b, real_dump_bytes, step="b")
    pointer_after_b = backup_service._read_current_db_filename()

    if trigger_b in _LIVE_CAPTURE:
        # Live-capturing triggers must move Current to the just-created dump,
        # regardless of whether one was set before.
        assert pointer_after_b == dump_b.filename, (
            f"trigger B ({trigger_b}) must move Current forward to {dump_b.filename}; "
            f"pointer is {pointer_after_b}"
        )
        assert dump_b.is_current is True
        assert dump_b.filename != dump_a.filename
    else:  # upload
        assert pointer_after_b == pointer_after_a, (
            f"trigger B (upload) must not touch the pointer; "
            f"was {pointer_after_a}, became {pointer_after_b}"
        )
        assert dump_b.is_current is False
