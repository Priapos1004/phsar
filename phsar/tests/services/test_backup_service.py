"""Tests for backup_service.

These exercise the real pg_dump / pg_restore subprocesses against the test
database. Each test gets its own tmp backup directory via monkeypatch on
settings.BACKUP_DIR, so no state leaks out to the real /backups volume.
"""

import io
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import UploadFile
from sqlalchemy import text

from app.core.config import settings
from app.core.db import async_session_maker
from app.exceptions import DuplicateBackupError
from app.models.job import Job, JobKind, JobStatus
from app.schemas.backup_schema import BackupIntegrity, BackupMetadata, BackupSource
from app.services import backup_service
from app.services._pg_subprocess import run_capture


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
    """pre_restore snapshots dedupe silently (like cron) so repeat restores of
    the same-state dump don't pile up no-op snapshots."""
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


async def test_retention_pins_current_dump_against_eviction(
    backup_dir, monkeypatch, unique_hashes,
):
    """Without the is_current keep-set exemption, a stack of unique creates
    pushes an older pinned dump out of the 14-recent window and retention
    deletes it — even though the bell still labels it 'matches live DB'."""
    pinned = await backup_service.create_backup(source=BackupSource.cron, label="pinned")

    # Force pinned 120 days into the past so it falls outside the 14-recent
    # window once 15 fresh dumps land. Deleting the sidecar makes
    # `list_backups` rebuild created_at from the file mtime.
    pinned_path = backup_dir / pinned.filename
    old_ts = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
    os.utime(pinned_path, (old_ts, old_ts))
    (pinned_path.parent / f"{pinned.filename}.meta.json").unlink()

    for i in range(15):
        await backup_service.create_backup(source=BackupSource.cron, label=f"fresh{i}")

    # Unique creates re-stamped the pointer to themselves; restore the
    # post-restore / post-dedupe state where Current sits on the older dump.
    backup_service._mark_current_db_confirmed(pinned.filename)

    deleted = await backup_service.apply_retention()
    assert pinned.filename not in deleted
    assert pinned_path.is_file()


async def test_retention_caps_uploaded_dumps(backup_dir):
    """Uploaded dumps were previously retention-exempt; that lets disk grow
    without bound at 2 GiB per upload. Retention now caps uploads at the
    most-recent _UPLOAD_RETENTION_COUNT entries, but never evicts the
    is_current upload (covered by a separate assert below)."""
    cap = backup_service._UPLOAD_RETENTION_COUNT
    uploads = []
    for i in range(cap + 3):
        # Fabricate distinct dumps directly on disk — save_uploaded_backup
        # would byte-dedupe identical payloads, so we shortcut via the
        # internal helpers that the upload path uses.
        original_stem = f"fake-upload-{i}"
        filename = backup_service._build_filename(
            BackupSource.upload, original_stem,
        )
        path = backup_dir / filename
        path.write_bytes(f"distinct-payload-{i}".encode())
        # Touch each upload at a distinct mtime so list_backups orders them.
        # Older uploads should evict; newer ones should survive.
        mtime = (
            datetime.now(timezone.utc) - timedelta(minutes=cap + 3 - i)
        ).timestamp()
        os.utime(path, (mtime, mtime))
        uploads.append(filename)

    survivors_before = {p.name for p in backup_dir.glob("*-upload*.dump")}
    assert len(survivors_before) == cap + 3

    deleted = await backup_service.apply_retention()
    survivors_after = {p.name for p in backup_dir.glob("*-upload*.dump")}

    # Oldest 3 uploads got evicted; the cap-sized newest pool survived.
    assert len(survivors_after) == cap
    assert set(deleted) >= {uploads[0], uploads[1], uploads[2]}
    for survivor in uploads[3:]:
        assert survivor in survivors_after


async def test_retention_pins_is_current_upload_against_eviction(backup_dir):
    """If admin restored from an uploaded dump, the is_current pointer lands
    on that upload. Retention must never evict the pointed-at upload, even
    if it's outside the most-recent _UPLOAD_RETENTION_COUNT window."""
    cap = backup_service._UPLOAD_RETENTION_COUNT
    pinned_filename = backup_service._build_filename(
        BackupSource.upload, "pinned-restore",
    )
    pinned_path = backup_dir / pinned_filename
    pinned_path.write_bytes(b"pinned-upload-payload")

    # Age the pinned upload past every other upload so the natural cap
    # window would evict it.
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
    os.utime(pinned_path, (old_ts, old_ts))

    backup_service._mark_current_db_restored(pinned_filename)

    for i in range(cap + 2):
        fresh = backup_service._build_filename(
            BackupSource.upload, f"fresh-{i}",
        )
        path = backup_dir / fresh
        path.write_bytes(f"fresh-payload-{i}".encode())

    deleted = await backup_service.apply_retention()
    assert pinned_filename not in deleted
    assert pinned_path.is_file()


# ---------------------------------------------------------------------------
# Retention pools, naming/pin, restore linking (v0.14.6)
# ---------------------------------------------------------------------------


def _fabricate_dump(
    backup_dir,
    *,
    source: BackupSource,
    created_at: datetime,
    label: str,
    name: str | None = None,
    restored_to: str | None = None,
    integrity: BackupIntegrity = BackupIntegrity.ok,
):
    """Write a dump file + sidecar directly to disk, bypassing pg_dump. The
    sidecar's created_at drives list_backups ordering + Sunday detection, so
    tests can craft any timeline without minute-of-wall-clock collisions.
    Distinct labels keep filenames unique within the same second."""
    filename = backup_service._build_filename(source, label)
    path = backup_dir / filename
    path.write_bytes(f"payload-{label}".encode())
    meta = BackupMetadata(
        filename=filename,
        size_bytes=path.stat().st_size,
        created_at=created_at,
        integrity=integrity,
        source=source,
        content_hash=f"hash-{label}",
        name=name,
        restored_to=restored_to,
    )
    backup_service._write_meta(path, meta)
    return filename


def _recent_sunday(reference: datetime) -> datetime:
    """An old Sunday well outside the 14-recent window (~100 days back)."""
    day = reference - timedelta(days=100)
    while day.weekday() != 6:
        day += timedelta(days=1)
    return day


def test_latest_per_sunday_keeps_one_per_distinct_sunday():
    """The bug fix: several dumps on one Sunday must collapse to that Sunday's
    latest, not each consume a weekly slot. Result is the latest dump per
    distinct Sunday, capped at `weeks` most-recent Sundays."""
    now = datetime.now(timezone.utc)
    sun_a = _recent_sunday(now)
    sun_b = sun_a - timedelta(days=7)

    def fake(created_at, fname):
        return BackupMetadata(
            filename=fname, size_bytes=1, created_at=created_at,
            integrity=BackupIntegrity.ok, source=BackupSource.cron,
        )

    a_early = fake(sun_a.replace(hour=2), "a-early")
    a_late = fake(sun_a.replace(hour=20), "a-late")
    b_only = fake(sun_b.replace(hour=12), "b-only")
    weekday = fake((sun_a + timedelta(days=1)).replace(hour=12), "weekday")

    # Newest-first, as list_backups returns.
    candidates = sorted(
        [a_early, a_late, b_only, weekday],
        key=lambda m: m.created_at, reverse=True,
    )
    kept = backup_service._latest_per_sunday(candidates, weeks=8)
    kept_names = {m.filename for m in kept}

    assert kept_names == {"a-late", "b-only"}  # one per Sunday, weekday ignored
    assert "a-early" not in kept_names


async def test_retention_keeps_latest_dump_per_sunday(backup_dir):
    """End-to-end: multiple manual dumps on one old Sunday keep only the
    latest as that week's archival representative; the rest age out."""
    now = datetime.now(timezone.utc)
    sunday = _recent_sunday(now)

    early = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=sunday.replace(hour=1), label="sun-early",
    )
    mid = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=sunday.replace(hour=12), label="sun-mid",
    )
    late = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=sunday.replace(hour=23), label="sun-late",
    )
    # Fill the 14-recent window with newer non-Sunday dumps so the Sunday
    # dumps are kept (or not) purely by the per-Sunday rule.
    for i in range(14):
        _fabricate_dump(
            backup_dir, source=BackupSource.manual,
            created_at=now - timedelta(minutes=i), label=f"recent{i}",
        )
    deleted = await backup_service.apply_retention()

    assert late not in deleted  # latest on the Sunday survives
    assert early in deleted and mid in deleted  # earlier same-Sunday dumps go


async def test_retention_pre_restore_not_treated_as_archival_sunday(backup_dir):
    """A pre-restore created on a Sunday must NOT win the archival weekly slot
    — pre-restores are rollback points, governed by their own relevance pool,
    not the manual/cron Sunday history. Asserts the manual weekly archive
    survives while a same-Sunday pre-restore ages out via the buffer."""
    now = datetime.now(timezone.utc)
    sunday = _recent_sunday(now)

    weekly = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=sunday.replace(hour=2), label="weekly",
    )
    # A pre-restore taken LATER the same Sunday — under a naive unified
    # latest-per-Sunday rule it would shadow `weekly`. It must not.
    pr_old = _fabricate_dump(
        backup_dir, source=BackupSource.pre_restore,
        created_at=sunday.replace(hour=23), label="pr-old",
    )
    # Three newer pre-restores fill the relevance buffer so pr_old is the one
    # that ages out — proving eviction is by recency, not a Sunday slot.
    pr_recent = [
        _fabricate_dump(
            backup_dir, source=BackupSource.pre_restore,
            created_at=now - timedelta(days=d), label=f"pr{d}",
        )
        for d in (1, 2, 3)
    ]
    for i in range(14):
        _fabricate_dump(
            backup_dir, source=BackupSource.manual,
            created_at=now - timedelta(minutes=i), label=f"recent{i}",
        )

    deleted = await backup_service.apply_retention()

    assert weekly not in deleted  # archival Sunday rep survives
    assert pr_old in deleted  # same-Sunday pre-restore evicted by relevance pool
    for pr in pr_recent:
        assert pr not in deleted  # buffer keeps the most-recent pre-restores


async def test_retention_keeps_pre_restore_tied_to_current(backup_dir):
    """The pre-restore snapshot whose restored_to matches the current pointer
    is the active rollback point and must survive even when old and beyond the
    recency buffer."""
    now = datetime.now(timezone.utc)
    current = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=now, label="current",
    )
    backup_service._mark_current_db_restored(current)

    linked = _fabricate_dump(
        backup_dir, source=BackupSource.pre_restore,
        created_at=now - timedelta(days=200), label="linked",
        restored_to=current,
    )
    # Push it out of the recency buffer with newer pre-restores.
    for d in (1, 2, 3):
        _fabricate_dump(
            backup_dir, source=BackupSource.pre_restore,
            created_at=now - timedelta(days=d), label=f"pr{d}",
        )

    deleted = await backup_service.apply_retention()
    assert linked not in deleted


async def test_retention_pins_named_backup(backup_dir):
    """A non-empty name pins a dump against auto-retention; clearing it
    re-exposes the dump to eviction."""
    now = datetime.now(timezone.utc)
    named = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=now - timedelta(days=300), label="keepme",
        name="keep this forever",
    )
    # Bury it under 14 newer dumps so only the name pin can save it.
    for i in range(14):
        _fabricate_dump(
            backup_dir, source=BackupSource.manual,
            created_at=now - timedelta(minutes=i), label=f"recent{i}",
        )

    deleted = await backup_service.apply_retention()
    assert named not in deleted

    # Clear the name → next retention pass evicts it.
    await backup_service.set_backup_name(named, None)
    deleted_again = await backup_service.apply_retention()
    assert named in deleted_again


async def test_retention_named_backups_do_not_consume_recent_slots(backup_dir):
    """Named (pinned) dumps are kept ON TOP of a full rolling window — they
    must not occupy the 14 recent slots. Otherwise pinning ~14 dumps would
    fill the window and evict every fresh auto-managed nightly backup."""
    now = datetime.now(timezone.utc)
    # 14 named dumps, all newer than the auto dump below.
    for i in range(14):
        _fabricate_dump(
            backup_dir, source=BackupSource.manual,
            created_at=now - timedelta(minutes=i), label=f"named{i}",
            name=f"keep {i}",
        )
    # A single un-named, auto-managed dump, older than every named one. With
    # the old slot-counting (named included) it would fall outside the top 14
    # and be evicted; the fix keeps it as the sole auto-managed recent dump.
    auto = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=now - timedelta(days=1), label="auto",
    )

    deleted = await backup_service.apply_retention()
    assert auto not in deleted


async def test_set_backup_name_sets_trims_and_clears(backup_dir):
    """Rename persists a trimmed name; blank/whitespace clears it (None)."""
    dump = await backup_service.create_backup(source=BackupSource.cron)

    named = await backup_service.set_backup_name(dump.filename, "  My Snapshot  ")
    assert named.name == "My Snapshot"
    assert (await backup_service.list_backups())[0].name == "My Snapshot"

    cleared = await backup_service.set_backup_name(dump.filename, "   ")
    assert cleared.name is None
    assert (await backup_service.list_backups())[0].name is None


async def test_list_backups_stamps_previous_state_on_current(backup_dir):
    """When the current state came from a restore, list_backups stamps the
    current row with the pre-restore snapshot it superseded."""
    now = datetime.now(timezone.utc)
    restored = _fabricate_dump(
        backup_dir, source=BackupSource.manual,
        created_at=now, label="restored",
    )
    pre = _fabricate_dump(
        backup_dir, source=BackupSource.pre_restore,
        created_at=now - timedelta(minutes=1), label="pre",
        restored_to=restored,
    )
    backup_service._mark_current_db_restored(restored)

    items = await backup_service.list_backups()
    current_row = next(m for m in items if m.filename == restored)
    assert current_row.is_current is True
    assert current_row.previous_state == pre


# ---------------------------------------------------------------------------
# Jobs-table staging + restore audit row (v0.14.2)
# ---------------------------------------------------------------------------


async def _create_jobs_with_statuses(statuses: list[JobStatus]) -> list[int]:
    """Create one Job per status, return their ids. Caller is responsible
    for cleanup via the `tracked_jobs` fixture."""
    ids: list[int] = []
    async with async_session_maker() as s:
        for status in statuses:
            job = Job(kind=JobKind.user_scrape, status=status, payload={})
            s.add(job)
            await s.flush()
            ids.append(job.id)
        await s.commit()
    return ids


async def _staging_row_ids() -> list[int]:
    async with async_session_maker() as s:
        result = await s.execute(text(
            f"SELECT id FROM {backup_service._JOBS_DUMP_STAGING_TABLE} ORDER BY id"
        ))
        return [r[0] for r in result.fetchall()]


async def _drop_staging_if_exists() -> None:
    async with async_session_maker() as s:
        await s.execute(text(
            f"DROP TABLE IF EXISTS {backup_service._JOBS_DUMP_STAGING_TABLE}"
        ))
        await s.commit()


async def test_stage_jobs_includes_only_terminal_status_rows(tracked_jobs):
    """Staging captures only succeeded + failed rows. Queued and running
    rows would resurrect as zombies after restore (no in-process worker
    driving them); excluding them at dump time is what makes the post-
    restore jobs table sane."""
    ids = await _create_jobs_with_statuses([
        JobStatus.queued, JobStatus.running, JobStatus.succeeded, JobStatus.failed,
    ])
    tracked_jobs.extend(ids)
    queued_id, running_id, succeeded_id, failed_id = ids

    try:
        await backup_service._stage_jobs_for_dump()
        staged = await _staging_row_ids()
        assert succeeded_id in staged
        assert failed_id in staged
        assert queued_id not in staged
        assert running_id not in staged
    finally:
        await _drop_staging_if_exists()


async def test_drop_jobs_staging_is_idempotent(tracked_jobs):
    """Always-called-in-finally pattern: a fresh-on-disk install or a
    sequential failure must not raise on a missing staging table."""
    # Drop twice on a no-table-exists state.
    await backup_service._drop_jobs_staging()
    await backup_service._drop_jobs_staging()


async def test_backup_dump_excludes_live_jobs_data_and_includes_staging(backup_dir):
    """Jobs ROW data must NOT appear in the dump's TOC, but the table
    schema MUST (without DDL in the dump, pg_restore --clean fails to
    drop `users` because jobs.requested_by_user_id keeps a live FK on
    users(id) — see the --exclude-table-data comment in
    backup_service.create_backup). `_jobs_dump_staging` is dumped so
    the audit rows ride through.
    """
    meta = await backup_service.create_backup(source=BackupSource.manual)
    dump_path = backup_dir / meta.filename

    returncode, stdout, _ = await run_capture(
        ["pg_restore", "--list", str(dump_path)], env=os.environ.copy(),
    )
    assert returncode == 0
    toc = stdout.decode(errors="replace")

    # `TABLE DATA public jobs` is the row-data entry; absent under
    # --exclude-table-data. The bare `TABLE public jobs` schema entry
    # SHOULD still be present.
    assert "TABLE DATA public jobs " not in toc, (
        f"Live jobs row data leaked into dump TOC:\n{toc}"
    )
    assert "TABLE public jobs " in toc, (
        f"Jobs schema missing from dump TOC — restore will fail on the "
        f"users FK:\n{toc}"
    )
    assert backup_service._JOBS_DUMP_STAGING_TABLE in toc, (
        f"Staging table missing from dump TOC:\n{toc}"
    )


async def test_merge_audit_inserts_restore_row_and_drops_staging(tracked_jobs):
    """Post-restore: the staging table left by pg_restore is merged into
    live jobs (no-op if empty) and the restore operation itself lands as
    a Job row at status=succeeded with payload pointing back at the dump
    + the pre-restore snapshot. The staging table is dropped so a future
    backup's CREATE TABLE doesn't trip on a stale leftover."""
    # Simulate what pg_restore brings in: a populated staging table.
    async with async_session_maker() as s:
        await s.execute(text(
            f"DROP TABLE IF EXISTS {backup_service._JOBS_DUMP_STAGING_TABLE}"
        ))
        # Mirror the real `jobs` schema for the staging table; the merge
        # is `INSERT INTO jobs SELECT * FROM staging`, so the column lists
        # must align. CREATE TABLE LIKE copies the schema cleanly without
        # us re-listing 12 columns by hand.
        await s.execute(text(
            f"CREATE TABLE {backup_service._JOBS_DUMP_STAGING_TABLE} "
            "(LIKE jobs INCLUDING ALL)"
        ))
        await s.commit()

    try:
        await backup_service._merge_jobs_audit_and_record_restore(
            filename="phsar-20260517T150000Z-manual.dump",
            pre_snapshot_filename="phsar-20260517T145959Z-pre_restore.dump",
            caller_username="admin-test",
            caller_user_id=None,  # FK nullable; avoids needing a real user row
            error=None,
        )

        # Staging dropped.
        async with async_session_maker() as s:
            exists = await s.scalar(text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = current_schema() "
                f"  AND table_name = '{backup_service._JOBS_DUMP_STAGING_TABLE}'"
                ")"
            ))
            assert exists is False

            # Restore Job row landed.
            result = await s.execute(
                Job.__table__.select().where(
                    Job.kind == JobKind.restore,
                    Job.payload["filename"].astext == "phsar-20260517T150000Z-manual.dump",
                )
            )
            rows = result.fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert row.status == JobStatus.succeeded
            assert row.payload["pre_snapshot_filename"] == "phsar-20260517T145959Z-pre_restore.dump"
            assert row.payload["caller_username"] == "admin-test"
            # Track for cleanup.
            tracked_jobs.append(row.id)
    finally:
        await _drop_staging_if_exists()


async def test_merge_audit_records_failed_restore_with_error_message(tracked_jobs):
    """A failed pg_restore (e.g. FK-blocked DROP, disk full, corrupt
    dump) must land in the jobs table at status=failed with the original
    error message preserved — otherwise the audit log lies and admins
    can't tell from `jobs` alone that the restore didn't actually
    happen. The staging-table merge is skipped on failure because the
    schema may be half-dropped and the INSERT would error too."""
    error_msg = "pg_restore: error: could not execute query: ERROR: cannot drop ..."
    await backup_service._merge_jobs_audit_and_record_restore(
        filename="bad-restore.dump",
        pre_snapshot_filename="bad-restore-pre.dump",
        caller_username="admin-test",
        caller_user_id=None,
        error=error_msg,
    )

    async with async_session_maker() as s:
        result = await s.execute(
            Job.__table__.select().where(
                Job.kind == JobKind.restore,
                Job.payload["filename"].astext == "bad-restore.dump",
            )
        )
        rows = result.fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row.status == JobStatus.failed
        assert row.error_message == error_msg
        tracked_jobs.append(row.id)


async def test_merge_audit_on_conflict_preserves_live_row(tracked_jobs):
    """A staged row whose id collides with a live row must NOT overwrite
    — live state reflects more-recent reality (e.g. a job that was
    'running' in the dump's snapshot moved to 'succeeded' after the
    snapshot but before the restore was triggered)."""
    live_ids = await _create_jobs_with_statuses([JobStatus.succeeded])
    tracked_jobs.extend(live_ids)
    live_id = live_ids[0]

    # Mark the live row with a distinguishing payload so we can detect
    # whether the merge overwrote it.
    async with async_session_maker() as s:
        await s.execute(text(
            "UPDATE jobs SET payload = '{\"marker\": \"live\"}'::jsonb WHERE id = :id"
        ).bindparams(id=live_id))
        await s.commit()

        await s.execute(text(
            f"DROP TABLE IF EXISTS {backup_service._JOBS_DUMP_STAGING_TABLE}"
        ))
        await s.execute(text(
            f"CREATE TABLE {backup_service._JOBS_DUMP_STAGING_TABLE} "
            "(LIKE jobs INCLUDING ALL)"
        ))
        # Insert a STAGING row with the SAME id but a different marker —
        # ON CONFLICT DO NOTHING means the live marker should survive.
        await s.execute(text(
            f"INSERT INTO {backup_service._JOBS_DUMP_STAGING_TABLE} "
            "(id, uuid, kind, status, payload, items_done, created_at, modified_at) "
            "VALUES (:id, gen_random_uuid(), 'user_scrape', 'succeeded', "
            "  '{\"marker\": \"staged\"}'::jsonb, 0, NOW(), NOW())"
        ).bindparams(id=live_id))
        await s.commit()

    try:
        await backup_service._merge_jobs_audit_and_record_restore(
            filename="conflict-test.dump",
            pre_snapshot_filename="conflict-test-pre.dump",
            caller_username="admin-test",
            caller_user_id=None,
            error=None,
        )

        async with async_session_maker() as s:
            row = (await s.execute(
                Job.__table__.select().where(Job.id == live_id)
            )).fetchone()
            assert row.payload == {"marker": "live"}

            # The restore-row insert still landed.
            restore_rows = (await s.execute(
                Job.__table__.select().where(
                    Job.kind == JobKind.restore,
                    Job.payload["filename"].astext == "conflict-test.dump",
                )
            )).fetchall()
            assert len(restore_rows) == 1
            tracked_jobs.append(restore_rows[0].id)
    finally:
        await _drop_staging_if_exists()


async def test_merge_audit_advances_jobs_id_seq_past_staging_max(tracked_jobs):
    """After merging staging rows, jobs_id_seq must point past the max
    inserted id — otherwise the restore_job INSERT (and every subsequent
    job creation) can collide with a freshly-merged row and IntegrityError
    out. Simulates a staging row with an id far above whatever the live
    sequence currently sits at."""
    # Pick an id that's almost certainly higher than the live sequence value
    # in a freshly-initialized test DB. The setval() inside the merge step
    # should advance past this floor.
    high_id = 1_000_000_001
    async with async_session_maker() as s:
        await s.execute(text(
            f"DROP TABLE IF EXISTS {backup_service._JOBS_DUMP_STAGING_TABLE}"
        ))
        await s.execute(text(
            f"CREATE TABLE {backup_service._JOBS_DUMP_STAGING_TABLE} "
            "(LIKE jobs INCLUDING ALL)"
        ))
        await s.execute(text(
            f"INSERT INTO {backup_service._JOBS_DUMP_STAGING_TABLE} "
            "(id, uuid, kind, status, payload, items_done, created_at, modified_at) "
            "VALUES (:id, gen_random_uuid(), 'user_scrape', 'succeeded', "
            "  '{}'::jsonb, 0, NOW(), NOW())"
        ).bindparams(id=high_id))
        await s.commit()
        tracked_jobs.append(high_id)

    try:
        await backup_service._merge_jobs_audit_and_record_restore(
            filename="seq-test.dump",
            pre_snapshot_filename="seq-test-pre.dump",
            caller_username="admin-test",
            caller_user_id=None,
            error=None,
        )

        async with async_session_maker() as s:
            # The restore row's id MUST be greater than the high staging id —
            # proves setval moved the sequence forward, so the INSERT got a
            # collision-free id allocated above the merged max.
            restore_rows = (await s.execute(
                Job.__table__.select().where(
                    Job.kind == JobKind.restore,
                    Job.payload["filename"].astext == "seq-test.dump",
                )
            )).fetchall()
            assert len(restore_rows) == 1
            assert restore_rows[0].id > high_id
            tracked_jobs.append(restore_rows[0].id)
    finally:
        await _drop_staging_if_exists()
