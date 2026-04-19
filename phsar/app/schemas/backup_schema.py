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


class BackupCreateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=40)


class BackupRestoreRequest(BaseModel):
    confirm: str
