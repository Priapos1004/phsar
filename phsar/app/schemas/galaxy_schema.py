from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class GalaxyGroupRename(BaseModel):
    # None or blank clears the hand name, so the group shows its auto name again.
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] | None


class GalaxyGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    name: str | None
    auto_name: str
