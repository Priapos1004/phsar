import asyncio
import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.exceptions import (
    BackupConfirmationMismatchError,
    BackupDiskSpaceError,
    BackupIntegrityError,
    BackupNotFoundError,
    BackupRestoreError,
    DuplicateBackupError,
)
from app.schemas.backup_schema import BackupIntegrity, BackupMetadata, BackupSource

# Filenames we accept: phsar-YYYYMMDD-HHMMSS[-suffix].dump.
# Anchored + restricted charset prevents path traversal via user-supplied filenames.
_FILENAME_PATTERN = re.compile(r"^phsar-\d{8}-\d{6}(-[a-z0-9][a-z0-9_-]*)?\.dump$")
_LABEL_SANITIZE_PATTERN = re.compile(r"[^a-z0-9_-]+")

# Floor, not a percentage — free-disk percentages are misleading on large drives
# (macOS APFS can report <5% free on a 500 GB SSD with 20+ GB actually available),
# and Phsar dumps are typically well under 100 MB, so 500 MB is ample headroom.
_DISK_SPACE_REQUIRED_BYTES = 500 * 1024 * 1024

_SOURCE_FILENAME_SUFFIX: dict[BackupSource, str] = {
    BackupSource.manual: "",
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
        suffix = f"{suffix}-{safe_label}" if suffix else f"-{safe_label}"
    return f"phsar-{_timestamp_string()}{suffix}.dump"


def _guess_source_from_name(filename: str) -> BackupSource:
    if "-cron" in filename:
        return BackupSource.cron
    if "-pre-restore" in filename:
        return BackupSource.pre_restore
    if "-upload" in filename:
        return BackupSource.upload
    return BackupSource.manual


def _validate_filename(filename: str) -> Path:
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


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


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


async def create_backup(
    source: BackupSource = BackupSource.manual,
    label: str | None = None,
) -> BackupMetadata:
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

    integrity = await _check_integrity(partial_path)
    if integrity != BackupIntegrity.ok:
        partial_path.unlink(missing_ok=True)
        raise BackupIntegrityError(filename, "pg_restore --list could not parse the dump")

    partial_path.rename(final_path)

    metadata = BackupMetadata(
        filename=filename,
        size_bytes=final_path.stat().st_size,
        created_at=_now_utc(),
        integrity=integrity,
        source=source,
        content_hash=_hash_file(final_path),
    )
    _write_meta(final_path, metadata)
    return metadata


async def list_backups() -> list[BackupMetadata]:
    backup_dir = _backup_dir()
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
        items.append(meta)
    items.sort(key=lambda m: m.created_at, reverse=True)
    return items


async def delete_backup(filename: str) -> None:
    path = _validate_filename(filename)
    path.unlink(missing_ok=True)
    _meta_path(path).unlink(missing_ok=True)


async def restore_backup(
    filename: str,
    confirm: str,
    caller_username: str,
) -> BackupMetadata:
    if confirm != caller_username:
        raise BackupConfirmationMismatchError()

    target_path = _validate_filename(filename)

    pre_snapshot = await create_backup(source=BackupSource.pre_restore)

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
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise BackupRestoreError(filename, stderr.decode(errors="replace").strip()[:500])

    return pre_snapshot


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


async def resolve_backup_path(filename: str) -> Path:
    """Validate + return an absolute path to a backup file. Used by the router to build
    a FileResponse without re-implementing filename validation."""
    return _validate_filename(filename)


async def save_uploaded_backup(upload_file: UploadFile) -> BackupMetadata:
    check_disk_space()

    original_stem = Path(upload_file.filename or "upload").stem
    filename = _build_filename(BackupSource.upload, original_stem)
    backup_dir = _backup_dir()
    partial_path = backup_dir / f"{filename}.partial"
    final_path = backup_dir / filename

    hasher = hashlib.sha256()
    try:
        with partial_path.open("wb") as f:
            while chunk := await upload_file.read(1024 * 1024):
                hasher.update(chunk)
                f.write(chunk)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    content_hash = hasher.hexdigest()

    integrity = await _check_integrity(partial_path)
    if integrity != BackupIntegrity.ok:
        partial_path.unlink(missing_ok=True)
        raise BackupIntegrityError(filename, "Uploaded file is not a valid pg custom dump")

    duplicate = await _find_duplicate(content_hash)
    if duplicate is not None:
        partial_path.unlink(missing_ok=True)
        raise DuplicateBackupError(duplicate.filename)

    partial_path.rename(final_path)

    metadata = BackupMetadata(
        filename=filename,
        size_bytes=final_path.stat().st_size,
        created_at=_now_utc(),
        integrity=integrity,
        source=BackupSource.upload,
        content_hash=content_hash,
    )
    _write_meta(final_path, metadata)
    return metadata
