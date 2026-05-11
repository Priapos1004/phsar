"""Dispatcher for the `backup` JobKind.

Notable design choices:

- **No maintenance bracket.** pg_dump runs on an MVCC snapshot and is
  read-only, so user writes are safe during a dump window. The
  maintenance gate is reserved for destructive operations (restore +
  sweeps) that would corrupt mid-flight requests.

- **Retention runs after every backup job.** Both manual and cron end
  with `apply_retention()` so the 14-recent + 8-Sunday + 1-known-good
  contract bounds disk usage on installs where cron is disabled or
  rarely fires. Manual + cron share the same retention pool.

- **Dedupe surfaces as success.** Manual `create_backup` normally raises
  `DuplicateBackupError` on content-hash match; the dispatcher converts
  that into a success outcome with `deduped_against` populated, so the
  bell renders 'Re-confirmed existing dump' instead of a 409-style fail.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DuplicateBackupError
from app.models.job import Job
from app.schemas.backup_schema import BackupSource
from app.services import backup_service
from app.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


async def backup_dispatcher(session: AsyncSession, job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    source_value = payload.get("source")
    if not source_value:
        raise ValueError(
            f"backup payload missing required 'source' field: {payload!r}",
        )
    source = BackupSource(source_value)
    label = payload.get("label")

    progress = ProgressReporter(job.id)
    await progress.update(stage="Dumping", force=True)

    deduped_against: str | None = None
    try:
        metadata = await backup_service.create_backup(source=source, label=label)
    except DuplicateBackupError as exc:
        # The exception carries the matched BackupMetadata directly, so
        # we don't pay a list_backups() rescan (which would shell out to
        # pg_restore --list for any dump missing a sidecar) just to
        # surface the dedupe in the result_summary.
        metadata = exc.existing_metadata
        deduped_against = metadata.filename

    await progress.update(stage="Applying retention", force=True)
    await backup_service.apply_retention()

    await progress.update(stage="Done", force=True)
    return {
        "filename": metadata.filename,
        "size_bytes": metadata.size_bytes,
        "integrity": metadata.integrity.value,
        "source": metadata.source.value,
        "deduped_against": deduped_against,
    }
