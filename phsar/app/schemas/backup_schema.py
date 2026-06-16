from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BackupIntegrity(str, Enum):
    ok = "ok"
    corrupt = "corrupt"
    unknown = "unknown"


class BackupSource(str, Enum):
    manual = "manual"
    cron = "cron"
    pre_restore = "pre_restore"
    upload = "upload"


class BackupMetadata(BaseModel):
    filename: str
    size_bytes: int
    created_at: datetime
    integrity: BackupIntegrity
    source: BackupSource
    # None for dumps written before the upload-dedupe check existed.
    # New dumps always get a hash; absent hash just opts out of the dedupe check.
    content_hash: str | None = None
    # Set at list time by matching against the .current_db.json pointer;
    # not stored on the per-dump sidecar. True for the dump whose content
    # matches the live DB — either because it was the last restore source,
    # or because a later dump's content_hash re-confirmed it.
    is_current: bool = False
    # Admin-given display name. Persisted in the sidecar. A non-empty name
    # PINS the dump against auto-retention (the admin actively chose to keep
    # it). Distinct from the creation-time `label` that becomes a filename
    # suffix — `name` never touches the filename, so it allows spaces/case.
    name: str | None = None
    # For a pre-restore snapshot: the filename of the backup that was restored
    # immediately after it. Persisted, set once at restore time. Lets the UI
    # match a pre-restore ("state before") to the restore it preceded, and
    # lets retention pin the snapshot tied to the current state.
    restored_to: str | None = None
    # Set at list time onto the is_current row: the pre-restore snapshot whose
    # `restored_to` equals the current filename (the "state before the current
    # restore"). Not persisted — derived like is_current.
    previous_state: str | None = None


class BackupCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=40)


class BackupRenameRequest(BaseModel):
    """A non-empty `name` pins the dump against auto-retention; null/blank
    clears the name (and the pin). Trimmed server-side."""
    name: str | None = Field(default=None, max_length=60)


class BackupRestoreRequest(BaseModel):
    confirm: str


class BackupJobPayload(BaseModel):
    """`extra='forbid'` so a router-side typo (e.g. `tag` instead of `label`)
    surfaces at job pickup instead of being silently dropped."""
    model_config = ConfigDict(extra="forbid")

    source: BackupSource
    label: str | None = None


class BackupResultSummary(BaseModel):
    """`deduped_against` is the matched dump's filename when create_backup
    found an existing dump with the same content hash; None for unique creates."""
    filename: str
    size_bytes: int
    integrity: BackupIntegrity
    source: BackupSource
    deduped_against: str | None = None
