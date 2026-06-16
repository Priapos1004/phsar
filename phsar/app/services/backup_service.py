import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import text

from app.core.config import settings
from app.core.db import async_session_maker, engine
from app.core.job_versions import make_job
from app.core.maintenance import set_maintenance
from app.exceptions import (
    BackupConfirmationMismatchError,
    BackupDiskSpaceError,
    BackupIntegrityError,
    BackupNotFoundError,
    BackupRestoreError,
    BackupUploadTooLargeError,
    DuplicateBackupError,
)
from app.models.job import JobKind, JobStatus
from app.schemas.backup_schema import BackupIntegrity, BackupMetadata, BackupSource
from app.services._pg_subprocess import run_capture

logger = logging.getLogger(__name__)

# Pointer to the dump whose content matches the live DB state. Updated on
# restore AND whenever a new dump's content_hash dedupe-matches an existing
# one (at which point the existing dump is re-confirmed as "current"). Lives
# in the backup directory (not inside the DB) because a restore would
# otherwise overwrite it with whatever the dump held at its creation time.
_CURRENT_DB_FILENAME = ".current_db.json"

# pg_restore -f - emits lines whose values change per invocation even when
# the underlying DB content is identical. Stripping them gives us a content-
# only hash so dedupe catches genuine no-op backups. Two families:
#   - timestamp/version comments wrapping the dump
#   - `\restrict <token>` / `\unrestrict <token>` psql meta-commands (anti-
#     privesc guard added in pg16+), whose tokens are freshly randomized on
#     every pg_restore run
_VARIABLE_LINE_RE = re.compile(
    rb"^(?:"
    rb"-- (?:Started on|Completed on|Dumped from database version|Dumped by pg_dump version) "
    rb"|\\(?:un)?restrict "
    rb")"
)

# Filenames we accept: phsar-YYYYMMDD-HHMMSS[-suffix].dump.
# Anchored + restricted charset prevents path traversal via user-supplied filenames.
_FILENAME_PATTERN = re.compile(r"^phsar-\d{8}-\d{6}(-[a-z0-9][a-z0-9_-]*)?\.dump$")
_LABEL_SANITIZE_PATTERN = re.compile(r"[^a-z0-9_-]+")

# Floor, not a percentage — free-disk percentages are misleading on large drives
# (macOS APFS can report <5% free on a 500 GB SSD with 20+ GB actually available),
# and Phsar dumps are typically well under 100 MB, so 500 MB is ample headroom.
_DISK_SPACE_REQUIRED_BYTES = 500 * 1024 * 1024

# Hard upper bound on uploaded dump size — above this we bail out mid-stream so a
# rogue admin request can't fill the backup volume (which would also knock out the
# scheduled-backup + pre-restore-snapshot paths).
_UPLOAD_MAX_BYTES = 2 * 1024 * 1024 * 1024
_UPLOAD_FREE_CHECK_EVERY_BYTES = 10 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024

# Most-recent uploads to keep on disk. Uploads were previously retention-exempt
# entirely (admin-managed), but at 2 GiB per upload the volume can grow without
# bound. The pointed-at (is_current) upload is always pinned regardless of age.
_UPLOAD_RETENTION_COUNT = 5

# Most-recent pre-restore snapshots to keep as a rollback buffer. Pre-restores
# are NOT archival backups — they're rollback points for the synchronous
# restore path. They get their own relevance-based pool (this buffer + the
# snapshot tied to the current state + named ones) instead of competing for
# the manual/cron Sunday/recent archival slots: a pre-restore's created_at is
# the restore moment, which could fall on a Sunday and pollute the long-term
# weekly history with throwaway pre-restore state.
_PRE_RESTORE_RETENTION_COUNT = 3

# Serializes every write path (create + upload) so concurrent manual + cron +
# re-upload requests can't race on disk-space checks, `.partial` filenames, or
# the dedupe lookup. Single-process assumption — scale horizontally and this
# needs a file lock.
_BACKUP_WRITE_LOCK = asyncio.Lock()

# Separator used on the manual-source filename so a manual backup labeled
# "cron" (unlikely but possible) produces "phsar-<ts>-manual-cron.dump"
# instead of "phsar-<ts>-cron.dump" — prevents _guess_source_from_name from
# misclassifying a label-only collision when the sidecar meta is missing.
_SOURCE_FILENAME_SUFFIX: dict[BackupSource, str] = {
    BackupSource.manual: "-manual",
    BackupSource.cron: "-cron",
    BackupSource.pre_restore: "-pre-restore",
    BackupSource.upload: "-upload",
}


def _backup_dir() -> Path:
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(dump_path: Path) -> Path:
    return dump_path.parent / f"{dump_path.name}.meta.json"


def _pg_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.DB_PASSWORD
    return env


def _pg_connection_args() -> list[str]:
    return [
        "-h", settings.DB_HOST,
        "-p", str(settings.DB_PORT),
        "-U", settings.DB_USER,
        "-d", settings.DB_NAME,
    ]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp_string() -> str:
    return _now_utc().strftime("%Y%m%d-%H%M%S")


def _sanitize_label(label: str | None) -> str | None:
    if not label:
        return None
    cleaned = _LABEL_SANITIZE_PATTERN.sub("-", label.strip().lower()).strip("-")
    return cleaned[:40] or None


def _build_filename(source: BackupSource, label: str | None) -> str:
    suffix = _SOURCE_FILENAME_SUFFIX[source]
    safe_label = _sanitize_label(label)
    if safe_label:
        suffix = f"{suffix}-{safe_label}"
    return f"phsar-{_timestamp_string()}{suffix}.dump"


def _guess_source_from_name(filename: str) -> BackupSource:
    # Order matters: if meta sidecar is missing for a manual backup whose
    # label happened to match another source token (e.g. "cron"), the
    # "-manual" segment wins over the later "-cron" substring.
    if "-manual" in filename:
        return BackupSource.manual
    if "-pre-restore" in filename:
        return BackupSource.pre_restore
    if "-cron" in filename:
        return BackupSource.cron
    if "-upload" in filename:
        return BackupSource.upload
    return BackupSource.manual


def get_backup_path(filename: str) -> Path:
    """Resolve a dump filename to its absolute path, raising BackupNotFoundError
    if the name doesn't match the safe pattern or the file doesn't exist. The
    single chokepoint every user-supplied filename (delete / restore / rename /
    reverify) flows through.

    `_FILENAME_PATTERN` is the path-traversal guard: it permits no path
    separators and no `..`, so the constructed path can never escape the backup
    dir. CodeQL flags the downstream sidecar file ops as `py/path-injection`
    because it doesn't model the regex as a sanitizer — those are dismissed as
    false positives (a resolve()/is_relative_to() containment check was tried
    and rejected: CodeQL doesn't credit it either, and it only adds noise)."""
    if not _FILENAME_PATTERN.match(filename):
        raise BackupNotFoundError(filename)
    path = _backup_dir() / filename
    if not path.is_file():
        raise BackupNotFoundError(filename)
    return path


def check_disk_space(required_bytes: int = _DISK_SPACE_REQUIRED_BYTES) -> None:
    usage = shutil.disk_usage(_backup_dir())
    if usage.free < required_bytes:
        raise BackupDiskSpaceError(usage.free, required_bytes)


def _current_db_path() -> Path:
    return _backup_dir() / _CURRENT_DB_FILENAME


def _read_current_db_filename() -> str | None:
    path = _current_db_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text()).get("filename")
    except Exception:
        return None


def _mark_current_db_restored(filename: str) -> None:
    now = _now_utc().isoformat()
    _current_db_path().write_text(json.dumps({
        "filename": filename, "confirmed_at": now, "restored_at": now,
    }))


def _mark_current_db_confirmed(filename: str) -> None:
    _current_db_path().write_text(json.dumps({
        "filename": filename, "confirmed_at": _now_utc().isoformat(),
    }))




async def _compute_content_hash(dump_path: Path) -> str:
    """Hash the logical content of a pg_dump custom-format archive.

    `pg_dump -Fc` output is not deterministic across runs of the same DB:
    the archive header embeds a creation timestamp, pg version strings, etc.
    We shell out to `pg_restore -f -` to stream the dump as plain SQL, strip
    the handful of lines that carry per-run values, and hash the remainder.
    Two dumps of an identical DB produce the same hash.

    Also stands in for an explicit integrity check: a corrupt archive makes
    `pg_restore -f -` exit non-zero, which this raises as BackupIntegrityError.
    """
    timeout = settings.BACKUP_RESTORE_TIMEOUT_SECONDS
    proc = await asyncio.create_subprocess_exec(
        "pg_restore", "-f", "-", str(dump_path),
        env=_pg_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None

    async def _hash_stdout() -> str:
        hasher = hashlib.sha256()
        buffer = b""
        while chunk := await proc.stdout.read(1024 * 1024):
            buffer += chunk
            lines = buffer.split(b"\n")
            buffer = lines.pop()
            for line in lines:
                if not _VARIABLE_LINE_RE.match(line):
                    hasher.update(line)
                    hasher.update(b"\n")
        if buffer and not _VARIABLE_LINE_RE.match(buffer):
            hasher.update(buffer)
        return hasher.hexdigest()

    try:
        # Drain stdout + stderr concurrently: pg_restore can emit enough
        # warnings to fill the ~64 KB pipe buffer, at which point it would
        # block on stderr while we're still reading stdout → deadlock.
        digest, stderr_bytes = await asyncio.wait_for(
            asyncio.gather(_hash_stdout(), proc.stderr.read()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise BackupIntegrityError(
            dump_path.name,
            f"pg_restore -f - exceeded the {timeout // 60}-minute timeout",
        ) from None
    await proc.wait()
    if proc.returncode != 0:
        raise BackupIntegrityError(
            dump_path.name,
            "pg_restore -f - failed: "
            + stderr_bytes.decode(errors="replace").strip()[:300],
        )
    return digest


async def _find_duplicate(content_hash: str) -> BackupMetadata | None:
    for existing in await list_backups():
        if existing.content_hash == content_hash:
            return existing
    return None


async def _check_integrity(dump_path: Path) -> BackupIntegrity:
    returncode, _, _ = await run_capture(
        ["pg_restore", "--list", str(dump_path)],
        env=_pg_env(),
        capture_stdout=False,
    )
    return BackupIntegrity.ok if returncode == 0 else BackupIntegrity.corrupt


def _write_meta(dump_path: Path, meta: BackupMetadata) -> None:
    _meta_path(dump_path).write_text(meta.model_dump_json())


def _read_meta(dump_path: Path) -> BackupMetadata | None:
    meta_file = _meta_path(dump_path)
    if not meta_file.is_file():
        return None
    try:
        return BackupMetadata.model_validate_json(meta_file.read_text())
    except Exception:
        return None


async def _set_meta_field(filename: str, **updates: object) -> BackupMetadata:
    """Read a dump's sidecar (rebuilding it if absent), apply field updates,
    and rewrite it. Shared by rename (`name`) and the restore-link stamp
    (`restored_to`). Returns the updated metadata with is_current re-stamped
    against the live pointer."""
    dump_path = get_backup_path(filename)
    # Honor the module's all-writes-serialized invariant so a rename can't
    # interleave its read-modify-write with another sidecar write.
    async with _BACKUP_WRITE_LOCK:
        meta = _read_meta(dump_path)
        if meta is None:
            meta = await _rebuild_meta(dump_path)
        meta = meta.model_copy(update=updates)
        _write_meta(dump_path, meta)
    if _read_current_db_filename() == filename:
        meta = meta.model_copy(update={"is_current": True})
    return meta


async def _rebuild_meta(dump_path: Path) -> BackupMetadata:
    integrity = await _check_integrity(dump_path)
    meta = BackupMetadata(
        filename=dump_path.name,
        size_bytes=dump_path.stat().st_size,
        created_at=datetime.fromtimestamp(dump_path.stat().st_mtime, tz=timezone.utc),
        integrity=integrity,
        source=_guess_source_from_name(dump_path.name),
    )
    _write_meta(dump_path, meta)
    return meta


async def _finalize_partial_dump(
    partial_path: Path,
    final_path: Path,
    source: BackupSource,
) -> tuple[BackupMetadata, bool]:
    """Shared tail for create + upload: hash → dedupe check → rename → write
    sidecar. Returns `(metadata, was_duplicate)` — callers decide whether a
    dedupe hit is an error (manual creates + uploads raise) or a silent
    return (cron + pre-restore), AND whether to move the Current pointer
    (live-capturing creates do, uploads don't)."""
    try:
        content_hash = await _compute_content_hash(partial_path)
    except BackupIntegrityError:
        partial_path.unlink(missing_ok=True)
        raise

    duplicate = await _find_duplicate(content_hash)
    if duplicate is not None:
        partial_path.unlink(missing_ok=True)
        return duplicate, True

    partial_path.rename(final_path)

    metadata = BackupMetadata(
        filename=final_path.name,
        size_bytes=final_path.stat().st_size,
        created_at=_now_utc(),
        integrity=BackupIntegrity.ok,
        source=source,
        content_hash=content_hash,
    )
    _write_meta(final_path, metadata)
    return metadata, False


# Name leads with an underscore so admins skimming `\dt` recognize it as
# a transient internal table, not part of the schema. Created and dropped
# inside `_BACKUP_WRITE_LOCK` so concurrent backups can't race the name.
_JOBS_DUMP_STAGING_TABLE = "_jobs_dump_staging"


async def _stage_jobs_for_dump() -> None:
    """Snapshot the terminal-state (succeeded/failed) `jobs` rows into a
    staging table that pg_dump will include in place of the live `jobs`
    table. Running/queued rows are intentionally excluded — the dump is
    a point-in-time MVCC snapshot, so in-flight rows would resurrect as
    zombies after restore (no in-process worker driving them).
    """
    async with async_session_maker() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {_JOBS_DUMP_STAGING_TABLE}"))
        await session.execute(text(
            f"CREATE TABLE {_JOBS_DUMP_STAGING_TABLE} AS "
            "SELECT * FROM jobs WHERE status IN ('succeeded', 'failed')"
        ))
        await session.commit()


async def _drop_jobs_staging() -> None:
    """Best-effort drop. Always called in a finally so a pg_dump crash
    can't leave the staging table behind for the next run to trip over."""
    try:
        async with async_session_maker() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {_JOBS_DUMP_STAGING_TABLE}"))
            await session.commit()
    except Exception:
        logger.exception("Failed to drop jobs-dump staging table")


async def create_backup(
    source: BackupSource = BackupSource.manual,
    label: str | None = None,
) -> BackupMetadata:
    async with _BACKUP_WRITE_LOCK:
        check_disk_space()

        filename = _build_filename(source, label)
        backup_dir = _backup_dir()
        partial_path = backup_dir / f"{filename}.partial"
        final_path = backup_dir / filename

        await _stage_jobs_for_dump()
        try:
            returncode, _, stderr = await run_capture(
                [
                    "pg_dump",
                    *_pg_connection_args(),
                    "-Fc",
                    # Skip jobs ROW data; its terminal rows ride in via
                    # `_jobs_dump_staging` (created above). The table
                    # schema is intentionally retained — without DDL in
                    # the dump, pg_restore --clean would fail to drop
                    # `users` because jobs.requested_by_user_id keeps a
                    # live FK on users(id). With --exclude-table-data the
                    # jobs table is dropped + recreated empty at restore
                    # time, the merge below repopulates the audit rows,
                    # and the live in-flight rows (if any) disappear
                    # alongside the rest of the rolled-back state.
                    "--exclude-table-data=jobs",
                    "-f", str(partial_path),
                ],
                env=_pg_env(),
            )
        finally:
            await _drop_jobs_staging()
        if returncode != 0:
            partial_path.unlink(missing_ok=True)
            raise BackupIntegrityError(filename, stderr.decode(errors="replace").strip()[:500])

        metadata, was_duplicate = await _finalize_partial_dump(
            partial_path, final_path, source,
        )
        # pg_dump just captured live state, so the resulting `metadata.filename`
        # IS the dump that matches live — whether it's a new unique dump or a
        # dedupe hit pointing at an existing one. Move Current to it.
        _mark_current_db_confirmed(metadata.filename)
        metadata = metadata.model_copy(update={"is_current": True})
        # Manual surfaces dedupe as a 409 so the admin sees a clear "identical
        # to X" error; cron / pre-restore silently return the matched dump so
        # unchanged DBs don't accumulate no-op snapshots.
        if was_duplicate and source == BackupSource.manual:
            raise DuplicateBackupError(metadata)
        return metadata


async def reverify_backups() -> dict[str, int]:
    """Re-run the cheap `pg_restore --list` integrity check on every dump and
    refresh the sidecar `integrity` when it changed.

    The create-time `integrity` flag is a point-in-time snapshot — without
    this, a dump that corrupts on disk after creation (truncation, bad
    sector, partial copy) keeps listing as `ok` forever, and retention trusts
    that flag for its `most recent known-good` pin. Cheap to run nightly:
    `--list` reads only the archive TOC, not the data, so it's sub-second per
    dump regardless of dump size (the full-decompress check, `pg_restore
    -f -`, stays reserved for create-time content hashing). Run BEFORE
    retention so the known-good pin reflects current disk state.
    """
    backup_dir = _backup_dir()
    checked = 0
    newly_corrupt = 0
    for meta in await list_backups():
        dump_path = backup_dir / meta.filename
        # Backup jobs don't bracket maintenance, so an admin delete can race
        # this loop. A vanished dump would otherwise read as `corrupt` and then
        # raise BackupNotFoundError on the sidecar rewrite, failing the whole
        # job — skip it instead of treating a deletion as corruption.
        if not dump_path.is_file():
            continue
        integrity = await _check_integrity(dump_path)
        checked += 1
        if integrity != meta.integrity:
            try:
                await _set_meta_field(meta.filename, integrity=integrity)
            except BackupNotFoundError:
                continue  # deleted between the is_file check and the rewrite
            if integrity == BackupIntegrity.corrupt:
                newly_corrupt += 1
                logger.warning(
                    "Backup %s failed re-verification — integrity %s -> corrupt",
                    meta.filename, meta.integrity.value,
                )
    return {"checked": checked, "newly_corrupt": newly_corrupt}


async def list_backups() -> list[BackupMetadata]:
    backup_dir = _backup_dir()
    current_filename = _read_current_db_filename()
    items: list[BackupMetadata] = []
    for path in backup_dir.glob("phsar-*.dump"):
        if not _FILENAME_PATTERN.match(path.name):
            continue
        meta = _read_meta(path)
        if meta is None:
            meta = await _rebuild_meta(path)
        else:
            actual_size = path.stat().st_size
            if meta.size_bytes != actual_size:
                meta = meta.model_copy(update={"size_bytes": actual_size})
        if current_filename and path.name == current_filename:
            meta = meta.model_copy(update={"is_current": True})
        items.append(meta)
    items.sort(key=lambda m: m.created_at, reverse=True)

    # Stamp the current row with the pre-restore snapshot it superseded (the
    # "state before the current restore"), if the current state came from a
    # restore. Derived here like is_current rather than persisted.
    if current_filename:
        # `m.filename != current_filename` guards the self-reference case:
        # restoring a dump whose content already equals the live DB dedupes the
        # pre-restore snapshot to the restore target itself, so its sidecar
        # carries `restored_to == own filename`. Without this guard the current
        # row would advertise itself as its own "previous state".
        prior = next(
            (
                m for m in items
                if m.restored_to == current_filename
                and m.filename != current_filename
            ),
            None,
        )
        if prior is not None:
            for i, m in enumerate(items):
                if m.filename == current_filename:
                    items[i] = m.model_copy(
                        update={"previous_state": prior.filename}
                    )
                    break
    return items


async def delete_backup(filename: str) -> None:
    path = get_backup_path(filename)
    path.unlink(missing_ok=True)
    _meta_path(path).unlink(missing_ok=True)
    if _read_current_db_filename() == filename:
        _current_db_path().unlink(missing_ok=True)


async def set_backup_name(filename: str, name: str | None) -> BackupMetadata:
    """Set (or clear) a dump's admin display name. A non-empty name pins the
    dump against auto-retention; a blank/None name clears the pin. The name is
    trimmed and never touches the filename (unlike the creation-time label)."""
    return await _set_meta_field(filename, name=(name or "").strip() or None)


async def restore_backup(
    filename: str,
    confirm: str,
    caller_username: str,
    caller_user_id: int,
) -> BackupMetadata:
    if confirm != caller_username:
        raise BackupConfirmationMismatchError()

    target_path = get_backup_path(filename)

    # Take the pre-restore snapshot BEFORE flipping the maintenance flag.
    # pg_dump is non-destructive and runs via subprocess (not through our
    # middleware), so there's no reason to block every user for the dump.
    pre_snapshot = await create_backup(source=BackupSource.pre_restore)

    set_maintenance(True)
    restore_error: str | None = None
    try:
        # pg_restore --clean needs ACCESS EXCLUSIVE locks to DROP tables.
        # Anything else holding even ACCESS SHARE makes it hang.
        # Close our own pool first, then kick off any stragglers (psql shells,
        # notebook sessions, etc.) before running the restore.
        await engine.dispose()
        # Double terminate with a short sleep: requests that slipped past the
        # maintenance gate before it flipped may still be acquiring fresh
        # connections here; the second pass catches those stragglers before
        # pg_restore hits DROP and hangs on their ACCESS SHARE locks.
        await _terminate_other_sessions()
        await asyncio.sleep(0.1)
        await _terminate_other_sessions()

        try:
            await _run_pg_restore(target_path, filename)
            _mark_current_db_restored(filename)
            # Link the pre-restore snapshot to the dump it preceded so the UI
            # can show "state before the current restore" and retention can
            # pin the snapshot tied to the now-current state.
            #
            # Dedup edge case: create_backup(pre_restore) dedupes silently, so
            # when the live DB already matched an existing dump (often a
            # manual/cron one) `pre_snapshot.filename` is THAT dump, and we
            # stamp restored_to onto its sidecar. That's intentional and
            # correct — the matched dump genuinely is the pre-restore state and
            # is already retained — but two consequences follow: (1) a
            # manual/cron sidecar can carry restored_to (only previous_state
            # derivation reads it; harmless), and (2) it's pinned by its own
            # archival rules, NOT the pre-restore pool's restored_to pin, so if
            # it ages out of the archival window the "Previous state" link
            # dangles. Acceptable; see services/CLAUDE.md.
            try:
                # Reassign so the returned metadata reflects the post-restore
                # pointer (is_current re-stamped) and the restored_to link,
                # instead of the stale snapshot captured at pre-restore create.
                pre_snapshot = await _set_meta_field(
                    pre_snapshot.filename, restored_to=filename
                )
            except Exception:
                logger.warning(
                    "Failed to stamp restored_to on pre-restore snapshot %s",
                    pre_snapshot.filename, exc_info=True,
                )
        except Exception as exc:
            # Captured for the audit row in `finally`; re-raised so HTTP still 5xx's.
            restore_error = str(exc)
            raise
    finally:
        # Prime the pool BEFORE lifting the maintenance gate so user requests
        # don't race the first post-restore connect (which would otherwise
        # flap Coolify's liveness probe). Bounded with wait_for so a broken
        # post-restore DB can't hang the finally block; if warm-up fails the
        # gate lifts anyway and the next request will surface the real error.
        try:
            async with engine.connect() as conn:
                await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=5.0)
        except Exception:
            logger.warning("Post-restore engine warm-up failed", exc_info=True)

        # Merge the restored audit rows back into the live `jobs` table and
        # append the restore Job row itself. `restore_error` is None on
        # success → status=succeeded; non-None on pg_restore failure →
        # status=failed with the original message preserved. Wrapped in
        # try/except + wait_for so the audit step can't deadlock the
        # maintenance gate — at worst the admin loses one operational log
        # line. The wait_for bound protects against a half-restored DB
        # where `async_session_maker()` hangs on connection acquisition.
        try:
            await asyncio.wait_for(
                _merge_jobs_audit_and_record_restore(
                    filename=filename,
                    pre_snapshot_filename=pre_snapshot.filename,
                    caller_username=caller_username,
                    caller_user_id=caller_user_id,
                    error=restore_error,
                ),
                timeout=30.0,
            )
        except Exception:
            logger.exception("Post-restore jobs-audit merge / restore-row insert failed")

        # set_maintenance writes a log line with stack-tag extraction; a
        # logger handler failure here would otherwise leave the flag
        # stuck across the rest of the request lifecycle. Catch + log so
        # the finally block always completes.
        try:
            set_maintenance(False)
        except Exception:
            logger.exception("set_maintenance(False) failed in restore finally")

    return pre_snapshot


async def _merge_jobs_audit_and_record_restore(
    *,
    filename: str,
    pre_snapshot_filename: str,
    caller_username: str,
    caller_user_id: int,
    error: str | None,
) -> None:
    """Merge the staged audit rows into the live `jobs` table (only on a
    successful pg_restore — a failed restore may have half-dropped the
    schema), then append a single Job row recording this restore itself.

    `caller_username` is denormed into the payload so deleting the admin
    user later doesn't erase the audit string. `error` carries the
    pg_restore failure message through to `error_message`.
    """
    async with async_session_maker() as session:
        if error is None:
            staging_exists = await session.scalar(text(
                "SELECT EXISTS ("
                "  SELECT 1 FROM information_schema.tables "
                "  WHERE table_schema = current_schema() "
                f"  AND table_name = '{_JOBS_DUMP_STAGING_TABLE}'"
                ")"
            ))
            if staging_exists:
                await session.execute(text(
                    f"INSERT INTO jobs SELECT * FROM {_JOBS_DUMP_STAGING_TABLE} "
                    "ON CONFLICT (id) DO NOTHING"
                ))
                await session.execute(text(f"DROP TABLE {_JOBS_DUMP_STAGING_TABLE}"))
                # Advance jobs_id_seq past max(id) so the next INSERT
                # (the restore_job below + every subsequent job creation)
                # can't collide with rows we just merged in. The restored
                # sequence value reflects whatever was next at dump time,
                # which may be ≤ staging's max id if the live DB issued
                # ids after the dump was taken.
                await session.execute(text(
                    "SELECT setval('jobs_id_seq', "
                    "GREATEST(COALESCE((SELECT MAX(id) FROM jobs), 0), 1))"
                ))

        now = datetime.now(timezone.utc)
        status = JobStatus.failed if error else JobStatus.succeeded
        restore_job = make_job(
            JobKind.restore,
            status=status,
            requested_by_user_id=caller_user_id,
            payload={
                "filename": filename,
                "pre_snapshot_filename": pre_snapshot_filename,
                "caller_username": caller_username,
            },
            result_summary={
                "restored_from": filename,
                "pre_restore_snapshot": pre_snapshot_filename,
            },
            error_message=error,
            started_at=now,
            finished_at=now,
        )
        session.add(restore_job)
        await session.commit()


async def _run_pg_restore(target_path: Path, filename: str) -> None:
    """Spawn pg_restore against the live DB, streaming into --clean --if-exists
    (drops + recreates every object). Caller owns the maintenance flag and
    pool-disposal lifecycle."""
    timeout = settings.BACKUP_RESTORE_TIMEOUT_SECONDS
    try:
        returncode, _, stderr = await run_capture(
            [
                "pg_restore",
                *_pg_connection_args(),
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                str(target_path),
            ],
            env=_pg_env(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Timeout mid-restore leaves the DB half-dropped. We don't auto-roll
        # back to the pre-snapshot because that restore could also time out
        # and compound the mess; instead, surface a clear error so the admin
        # knows to re-upload the pre-snapshot manually and bump
        # BACKUP_RESTORE_TIMEOUT_SECONDS.
        raise BackupRestoreError(
            filename,
            f"pg_restore exceeded the {timeout // 60}-minute timeout. "
            "The database is likely in a partially-restored state — re-run "
            "the restore against the pre-restore snapshot (see backups list) "
            "and raise BACKUP_RESTORE_TIMEOUT_SECONDS if the dump is larger "
            "than previously seen.",
        ) from None

    if returncode != 0:
        raise BackupRestoreError(filename, stderr.decode(errors="replace").strip()[:500])


async def _terminate_other_sessions() -> None:
    # Fire-and-forget: if psql fails we still try pg_restore. Better to hit the
    # real lock-wait error message than mask it behind a terminate failure. We
    # log stderr at WARNING so a missing psql binary or auth failure leaves a
    # breadcrumb for the "pg_restore hung on locks" postmortem.
    returncode, _, stderr = await run_capture(
        [
            "psql",
            *_pg_connection_args(),
            "-c",
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid();",
        ],
        env=_pg_env(),
        capture_stdout=False,
    )
    if returncode != 0 and stderr:
        logger.warning(
            "Terminate-other-sessions psql returned %s: %s",
            returncode,
            stderr.decode(errors="replace").strip()[:300],
        )


def _is_sunday_utc(dt: datetime) -> bool:
    return dt.weekday() == 6


def _latest_per_sunday(candidates: list[BackupMetadata], weeks: int) -> list[BackupMetadata]:
    """Return the latest dump on each of the most recent `weeks` distinct
    Sundays. `candidates` is newest-first (as `list_backups` returns), so the
    first dump seen for a given Sunday date IS that Sunday's latest — that's
    what we keep. Fixes the prior `[... ][:8]` slice, which kept the 8 most
    recent Sunday-*created* dumps and let several dumps from one busy Sunday
    consume every slot."""
    latest_by_date: dict[str, BackupMetadata] = {}
    for b in candidates:
        if not _is_sunday_utc(b.created_at):
            continue
        day = b.created_at.date().isoformat()  # serializable key, one per Sunday
        if day not in latest_by_date:  # first seen == latest (newest-first)
            latest_by_date[day] = b
    by_recency = sorted(
        latest_by_date.values(), key=lambda b: b.created_at, reverse=True,
    )
    return by_recency[:weeks]


async def apply_retention() -> list[str]:
    """Evict old backups. Three independent pools:

    - Archival (manual + cron): 14 most recent + the latest dump on each of
      the last 8 distinct Sundays + the most recent known-good dump,
      regardless of age.
    - Pre-restore: relevance-based, NOT archival. Pre-restores are rollback
      points, not weekly history, so they never compete for the Sunday/recent
      slots above. Keep the one tied to the current state, plus the
      `_PRE_RESTORE_RETENTION_COUNT` most recent as an "undo the undo" buffer;
      discard older ones once they're no longer relevant.
    - Uploads: the `_UPLOAD_RETENTION_COUNT` most recent.

    Every pool pins the `is_current` dump (matches the live DB) and any
    named dump (the admin actively chose to keep it) regardless of age. Named
    dumps are kept ON TOP of a full rolling window — they're filtered out
    before the recent/Sunday/cap slots are counted, so pinning a backup never
    starves the auto-managed window (else 14 pinned dumps would evict every
    fresh nightly backup).
    """
    backups = await list_backups()
    current_filename = _read_current_db_filename()
    deleted: list[str] = []

    def _auto(pool: list[BackupMetadata]) -> list[BackupMetadata]:
        # Slots are counted over auto-managed (un-pinned) dumps only; named
        # dumps are always kept via the pin below and must not consume slots.
        return [b for b in pool if not b.name]

    def _evict(pool: list[BackupMetadata], keep: set[str]) -> None:
        for b in pool:
            # Age-independent pins: is_current (matches live DB — a stack of
            # dedupe-hit re-confirms could otherwise push an older-but-pointed
            # -at dump out of the recent window) and any named dump (the admin
            # actively chose to keep it).
            if b.is_current or b.name or b.filename in keep:
                continue
            deleted.append(b.filename)

    # --- archival pool (manual + cron) -----------------------------------
    archival = [
        b for b in backups
        if b.source in (BackupSource.cron, BackupSource.manual)
    ]
    auto_archival = _auto(archival)
    keep: set[str] = (
        {b.filename for b in auto_archival[:14]}
        | {b.filename for b in _latest_per_sunday(auto_archival, weeks=8)}
    )
    # Trusts the sidecar integrity flag. The backup dispatcher runs
    # reverify_backups() immediately before retention so this reflects
    # current disk state; a future retention-only caller must reverify first
    # or this pin can crown a since-corrupted dump as "known good".
    most_recent_ok = next(
        (b for b in archival if b.integrity == BackupIntegrity.ok), None,
    )
    if most_recent_ok is not None:
        keep.add(most_recent_ok.filename)
    _evict(archival, keep)

    # --- pre-restore pool ------------------------------------------------
    # Relevance-based: the snapshot tied to the current state is the active
    # rollback point and is always kept; a small recency buffer covers a
    # chain of recent restores. Everything older ages out.
    pre_restores = [b for b in backups if b.source == BackupSource.pre_restore]
    pre_keep = {b.filename for b in _auto(pre_restores)[:_PRE_RESTORE_RETENTION_COUNT]}
    if current_filename is not None:
        # Guard against None == None pinning every unlinked pre-restore on a
        # fresh install (no pointer yet, restored_to also None).
        pre_keep.update(
            b.filename for b in pre_restores if b.restored_to == current_filename
        )
    _evict(pre_restores, pre_keep)

    # --- upload pool -----------------------------------------------------
    # Cap uploaded dumps to avoid unbounded disk growth — a 2 GiB upload cap
    # with no eviction would let an admin (or a runaway script) fill the
    # volume.
    uploads = [b for b in backups if b.source == BackupSource.upload]
    upload_keep = {b.filename for b in _auto(uploads)[:_UPLOAD_RETENTION_COUNT]}
    _evict(uploads, upload_keep)

    for filename in deleted:
        await delete_backup(filename)

    return deleted


async def save_uploaded_backup(upload_file: UploadFile) -> BackupMetadata:
    async with _BACKUP_WRITE_LOCK:
        check_disk_space()

        original_stem = Path(upload_file.filename or "upload").stem
        filename = _build_filename(BackupSource.upload, original_stem)
        backup_dir = _backup_dir()
        partial_path = backup_dir / f"{filename}.partial"
        final_path = backup_dir / filename

        try:
            bytes_written = 0
            last_disk_check = 0
            with partial_path.open("wb") as f:
                while chunk := await upload_file.read(_UPLOAD_CHUNK_BYTES):
                    bytes_written += len(chunk)
                    if bytes_written > _UPLOAD_MAX_BYTES:
                        raise BackupUploadTooLargeError(bytes_written, _UPLOAD_MAX_BYTES)
                    f.write(chunk)
                    # Recheck free space periodically so a slow upload that
                    # fills the disk while streaming can't knock out the
                    # scheduled-backup / pre-restore-snapshot paths.
                    if bytes_written - last_disk_check >= _UPLOAD_FREE_CHECK_EVERY_BYTES:
                        check_disk_space()
                        last_disk_check = bytes_written
        except Exception:
            partial_path.unlink(missing_ok=True)
            raise

        metadata, was_duplicate = await _finalize_partial_dump(
            partial_path, final_path, BackupSource.upload,
        )
        # Uploads never move the Current pointer — bytes are external and we
        # can't verify they represent live DB state. Stamp is_current
        # truthfully against whatever the pointer holds right now: for a
        # dedupe hit the matched dump may already be Current, for a unique
        # upload the new filename can't equal the unchanged pointer.
        pointer = _read_current_db_filename()
        metadata = metadata.model_copy(update={"is_current": metadata.filename == pointer})
        if was_duplicate:
            raise DuplicateBackupError(metadata)
        return metadata
