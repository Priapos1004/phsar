from uuid import UUID

from pydantic import BaseModel, field_validator

BULK_MEDIA_LIMIT = 50


class BulkMediaUuids(BaseModel):
    """Shared base for bulk media operations (ratings + watchlist): validates the
    media_uuids list (1..BULK_MEDIA_LIMIT)."""
    media_uuids: list[UUID]

    @field_validator("media_uuids")
    @classmethod
    def validate_media_uuids(cls, v: list[UUID]) -> list[UUID]:
        if len(v) > BULK_MEDIA_LIMIT:
            raise ValueError(f"Cannot bulk-operate on more than {BULK_MEDIA_LIMIT} media at once")
        if not v:
            raise ValueError("At least one media UUID is required")
        return v
