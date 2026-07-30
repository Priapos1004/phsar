from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BackupIntegrity(str, Enum):
    ok = "ok"
    corrupt = "corrupt"
    unknown = "unknown"


class BackupStatus(str, Enum):
    """Whether a dump is restorable RIGHT NOW — `integrity` composed with
    `schema_current`, in the order a reader cares about.

    Derived server-side (in `list_backups`) rather than in the UI so every
    consumer agrees: the Backups card renders it, the sort orders by it, and the
    startup self-heal decides on it. Composing it per-consumer is how the card
    comes to call a revision-less dump green while the self-heal treats the same
    row as unrestorable.

    `unknown` is NOT `ok`: an unstamped dump might restore cleanly, but nothing
    on disk says so, and a backup you can't vouch for isn't one you should be
    told to rely on. It stays distinct from `outdated` (which is a positive
    finding of staleness) so a legacy dump is never *accused*.
    """
    corrupt = "corrupt"
    outdated = "outdated"
    unknown = "unknown"
    ok = "ok"


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
    # The Alembic revision the DUMP carries, read out of its own
    # `alembic_version` table (not the live DB's) so an uploaded dump reports
    # what it actually holds. Persisted. None for dumps written before this
    # existed, and for a sidecar rebuilt from an orphaned dump — the cheap TOC
    # check can't recover it, same as content_hash.
    alembic_revision: str | None = None
    # Whether `alembic_revision` matches the live DB's. Set at list time, not
    # persisted — the answer changes under the dump every time a migration runs.
    # None = unknown (either side missing), which is deliberately NOT the same as
    # False: a legacy dump shouldn't be accused of being schema-stale.
    #
    # Kept OUT of `integrity`, which stays a pure file-corruption verdict, because
    # `apply_retention` pins the most-recent-ok dump as its known-good archival
    # anchor — folding a schema verdict in would leave retention with no anchor at
    # all immediately after every migration. The composite lives in `status`.
    schema_current: bool | None = None
    # `integrity` + `schema_current` composed into the one restorability verdict
    # every consumer reads. Derived at list time; see BackupStatus.
    status: BackupStatus = BackupStatus.unknown


class BackupListResponse(BaseModel):
    """The dump list plus the live DB's Alembic revision.

    An envelope rather than a bare list because `db_revision` is one
    process-global fact, not a per-dump one — denormalizing it onto N rows would
    be worse. It has to come from the server: the card previously read it back off
    whichever dump was `schema_current`, which made it unavailable in exactly the
    state it explains (right after a migration, when no dump matches and the
    "outdated" tooltip most needs to name what the dump is outdated *against*).
    `None` only when the revision genuinely can't be read.
    """
    db_revision: str | None
    backups: list[BackupMetadata]


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
