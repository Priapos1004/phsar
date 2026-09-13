"""Admin-reviewable removal candidates: catalogue entries that should probably
go, surfaced for a human decision instead of deleted automatically.

Third sibling to MergeCandidate / SplitCandidate, same review workflow. What the
detectors look for, and why nothing deletes on its own, is in
`docs/features/curation.md`; `detected_by` names which one raised the row.

Lifecycle:
- `pending` — a detector flagged it; admin needs to decide.
- `dismissed` — admin reviewed and chose to keep it. Sticky; see
  `docs/features/curation.md`.
- `deleted` — the media (and its anime, if that was the last one) is gone.
  `blacklisted` records whether the mal_id also went into `media_unwanted`.

Cascade: `media_id` is nullable with ON DELETE **SET NULL**, deliberately unlike
its two siblings. MergeCandidate cascades from anime, and that cascade is why
`merge()` never records a `merged` status — deleting the anime destroys the row.
A delete candidate *records* a deletion, so it has to outlive its target; CASCADE
would erase the audit trail at the exact moment it becomes the only record. The
identity snapshot (mal_id/title/name_*) is what survives, and mal_id is also the
key a later sweep would rediscover on and the key `media_unwanted` blocks on.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class DeleteCandidateStatus(str, enum.Enum):
    pending = "pending"
    dismissed = "dismissed"
    deleted = "deleted"


class DeleteCandidate(BaseModel):
    __tablename__ = "delete_candidates"

    # Nullable + SET NULL: see the module docstring. Null means "the media this
    # row describes has already been removed", which is the normal end state.
    media_id = Column(
        Integer,
        ForeignKey("media.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Identity snapshot, written at detection time. The only thing left once the
    # media row is gone.
    mal_id = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    name_eng = Column(String, nullable=True)
    name_jap = Column(String, nullable=True)

    # String, not Enum, so adding a future detector doesn't need a migration.
    # Mirrors merge_candidates.detected_by.
    detected_by = Column(String(32), nullable=False)  # "sweep_404", "low_signal"
    status = Column(
        Enum(DeleteCandidateStatus),
        nullable=False,
        default=DeleteCandidateStatus.pending,
    )
    # The admin's blacklist choice, not a cache of `media_unwanted`: the two are
    # separately mutable and this one is the record of what was decided here.
    blacklisted = Column(Boolean, nullable=False, server_default=text("false"))

    media = relationship("Media", foreign_keys=[media_id], lazy="raise")

    __table_args__ = (
        # One LIVE candidate per mal_id, so re-running detection is idempotent
        # while resolved rows still accumulate as history. Partial-unique rather
        # than a plain UniqueConstraint precisely because the history needs
        # repeats (dismiss -> resurface -> dismiss again).
        Index(
            "uq_delete_candidates_pending_mal_id",
            "mal_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # Admin list scans pending only; partial keeps it tiny as resolved rows
        # accumulate. Mirrors merge_candidates / split_candidates.
        Index(
            "ix_delete_candidates_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
