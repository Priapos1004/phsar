from uuid import UUID

from pydantic import BaseModel, field_validator
from pydantic_core import PydanticCustomError

BULK_MEDIA_LIMIT = 50


class BulkMediaUuids(BaseModel):
    """Shared base for bulk media operations (ratings + watchlist): validates the
    media_uuids list (1..BULK_MEDIA_LIMIT)."""
    media_uuids: list[UUID]

    @field_validator("media_uuids")
    @classmethod
    def validate_media_uuids(cls, v: list[UUID]) -> list[UUID]:
        # PydanticCustomError (not a bare ValueError) so the surfaced message is exactly
        # the text — a raised ValueError gets Pydantic's "Value error, " prefix, which
        # leaks into the user-facing 422 detail.
        if len(v) > BULK_MEDIA_LIMIT:
            raise PydanticCustomError(
                "too_many_media",
                "Cannot bulk-operate on more than {limit} media at once",
                {"limit": BULK_MEDIA_LIMIT},
            )
        if not v:
            raise PydanticCustomError("empty_media", "At least one media UUID is required")
        return v
