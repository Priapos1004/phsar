from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
    # Set at list time by matching against the .last_restored.json sidecar;
    # not stored on the per-dump sidecar.
    is_current_restore: bool = False


class BackupCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=40)


class BackupRestoreRequest(BaseModel):
    confirm: str
