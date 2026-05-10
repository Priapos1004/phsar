from datetime import datetime

from pydantic import BaseModel


class MaintenanceStatus(BaseModel):
    """Current maintenance state for the frontend pre-warning banner.

    `active` is True only while a sweep job is running. `scheduled_at` is the
    future moment a sweep will start; the banner counts down from there.
    Both can be set/clear independently — the typical sequence is:
    schedule → scheduled_at populated, active False → active flips True at
    job claim, scheduled_at cleared → both cleared at job finish.
    """

    active: bool
    scheduled_at: datetime | None
