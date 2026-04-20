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
from app.core.db import engine
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
from app.schemas.backup_schema import BackupIntegrity, BackupMetadata, BackupSource

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
    if the name doesn't match the safe pattern or the file doesn't exist."""
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


def _adopt_existing_as_current(partial_path: Path, duplicate: BackupMetadata) -> BackupMetadata:
    """Shared dedupe-hit tail: delete the partial and re-point the current-DB
    marker at the matched existing dump so the UI badge follows DB state."""
    partial_path.unlink(missing_ok=True)
    _mark_current_db_confirmed(duplicate.filename)
    return duplicate


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
    proc = await asyncio.create_subprocess_exec(
        "pg_restore", "--list", str(dump_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    return BackupIntegrity.ok if proc.returncode == 0 else BackupIntegrity.corrupt


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
    return (cron + pre-restore)."""
    try:
        content_hash = await _compute_content_hash(partial_path)
    except BackupIntegrityError:
        partial_path.unlink(missing_ok=True)
        raise

    duplicate = await _find_duplicate(content_hash)
    if duplicate is not None:
        return _adopt_existing_as_current(partial_path, duplicate), True

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

        args = [
            "pg_dump",
            *_pg_connection_args(),
            "-Fc",
            "-f", str(partial_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *args,
            env=_pg_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            partial_path.unlink(missing_ok=True)
            raise BackupIntegrityError(filename, stderr.decode(errors="replace").strip()[:500])

        metadata, was_duplicate = await _finalize_partial_dump(
            partial_path, final_path, source,
        )
        # Manual surfaces dedupe as a 409 so the admin sees a clear "identical
        # to X" error; cron / pre-restore silently return the matched dump so
        # unchanged DBs don't accumulate no-op snapshots.
        if was_duplicate and source == BackupSource.manual:
            raise DuplicateBackupError(metadata.filename)
        return metadata


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
    return items


async def delete_backup(filename: str) -> None:
    path = get_backup_path(filename)
    path.unlink(missing_ok=True)
    _meta_path(path).unlink(missing_ok=True)
    if _read_current_db_filename() == filename:
        _current_db_path().unlink(missing_ok=True)


async def restore_backup(
    filename: str,
    confirm: str,
    caller_username: str,
) -> BackupMetadata:
    if confirm != caller_username:
        raise BackupConfirmationMismatchError()

    target_path = get_backup_path(filename)

    # Take the pre-restore snapshot BEFORE flipping the maintenance flag.
    # pg_dump is non-destructive and runs via subprocess (not through our
    # middleware), so there's no reason to block every user for the dump.
    pre_snapshot = await create_backup(source=BackupSource.pre_restore)

    set_maintenance(True)
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

        await _run_pg_restore(target_path, filename)

        _mark_current_db_restored(filename)
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
        set_maintenance(False)

    return pre_snapshot


async def _run_pg_restore(target_path: Path, filename: str) -> None:
    """Spawn pg_restore against the live DB, streaming into --clean --if-exists
    (drops + recreates every object). Caller owns the maintenance flag and
    pool-disposal lifecycle."""
    timeout = settings.BACKUP_RESTORE_TIMEOUT_SECONDS
    args = [
        "pg_restore",
        *_pg_connection_args(),
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        str(target_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=_pg_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
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

    if proc.returncode != 0:
        raise BackupRestoreError(filename, stderr.decode(errors="replace").strip()[:500])


async def _terminate_other_sessions() -> None:
    # Fire-and-forget: if psql fails we still try pg_restore. Better to hit the
    # real lock-wait error message than mask it behind a terminate failure. We
    # log stderr at WARNING so a missing psql binary or auth failure leaves a
    # breadcrumb for the "pg_restore hung on locks" postmortem.
    args = [
        "psql",
        *_pg_connection_args(),
        "-c",
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = current_database() AND pid <> pg_backend_pid();",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        env=_pg_env(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and stderr:
        logger.warning(
            "Terminate-other-sessions psql returned %s: %s",
            proc.returncode,
            stderr.decode(errors="replace").strip()[:300],
        )


def _is_sunday_utc(dt: datetime) -> bool:
    return dt.weekday() == 6


async def apply_retention() -> list[str]:
    """Evict old backups. Keeps 14 most recent + last 8 Sunday dumps + the most recent
    known-good dump, regardless of date. Only touches manual + cron dumps: uploads and
    pre-restore snapshots are always preserved (admin-managed)."""
    backups = await list_backups()
    candidates = [
        b for b in backups
        if b.source in (BackupSource.cron, BackupSource.manual)
    ]

    sunday_keeps = [b for b in candidates if _is_sunday_utc(b.created_at)][:8]
    keep: set[str] = (
        {b.filename for b in candidates[:14]}
        | {b.filename for b in sunday_keeps}
    )

    most_recent_ok = next(
        (b for b in candidates if b.integrity == BackupIntegrity.ok),
        None,
    )
    if most_recent_ok is not None:
        keep.add(most_recent_ok.filename)

    deleted: list[str] = []
    for b in candidates:
        if b.filename not in keep:
            await delete_backup(b.filename)
            deleted.append(b.filename)
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
        if was_duplicate:
            raise DuplicateBackupError(metadata.filename)
        return metadata
