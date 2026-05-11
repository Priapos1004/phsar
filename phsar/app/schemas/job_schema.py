from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.job import JobKind, JobStatus


class ScrapeJobRequest(BaseModel):
    """The query is forwarded to MAL search; the dispatcher saves every
    matching anime + its connected media. Connected matches dedupe naturally
    via the BFS visited set, so no client-side disambiguation is needed.

    min_length=4 because shorter queries are ambiguous on MAL (e.g. "fma" hits
    Fullmetal Alchemist + dozens of unrelated entries) and waste a job slot.

    `mal_id` is opt-in: when set, the BFS skips the fuzzy q= lookup and
    seeds directly from the given mal_id. The seasonal sweep uses this
    so children don't pull unrelated top-3 matches into the catalog;
    user-facing callers can still submit `{query}` only.
    """
    query: str = Field(..., min_length=4, max_length=200)
    mal_id: int | None = Field(default=None, gt=0)


class JobResponse(BaseModel):
    """Frontend-facing view of a Job row. Excludes columns the bell doesn't
    need (modified_at, requested_by relationship).

    Well-known result_summary keys (set by JobWorker / dispatchers; not all
    are present on every row):
    - "retryable": bool — set on failed rows. False when the failure is a
      PermanentPhsarError or a missing-dispatcher config error; the bell
      hides its retry button when False.
    - "anime_count" / "media_count": int — set by user_scrape on success.
    """
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    kind: JobKind
    status: JobStatus
    payload: dict[str, Any]
    stage: str | None
    items_total: int | None
    items_done: int
    result_summary: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
