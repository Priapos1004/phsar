"""Admin-reviewable split-candidate rows surfaced by `find_disjoint_franchises`.

Sibling to MergeCandidate: same admin-review workflow, but the shape is
asymmetric — split has ONE source anime + N proposed cluster payloads,
where merge has TWO existing anime rows. The two can't share the same
schema cleanly (no anime_b_id, JSONB clusters payload), so it's a
separate table.

Lifecycle:
- `pending` — detection has flagged disjoint substance-passing main
  chains under this anime; admin needs to decide.
- `dismissed` — admin reviewed and chose to keep them bundled (e.g., a
  judgment call on Mononoke 2024 trilogy ↔ original Mononoke TV).
- `split` — execute_split has run; the rows have been re-parented and
  new anime rows created for each cluster.

Cascade: FK on `anime_id` with ON DELETE CASCADE so deleting the source
anime (merge-survivor reparent, manual delete) cleans up the row.
"""

import enum

from sqlalchemy import Column, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class SplitCandidateStatus(str, enum.Enum):
    pending = "pending"
    dismissed = "dismissed"
    split = "split"


class SplitCandidate(BaseModel):
    __tablename__ = "split_candidates"

    anime_id = Column(
        Integer,
        ForeignKey("anime.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JSONB list of DisjointFranchise dicts (see relation_classifier.py).
    # Each entry holds member_mal_ids, substance_member_mal_ids,
    # suggested_anchor_mal_id, bridge_edges.
    clusters = Column(JSONB, nullable=False)
    status = Column(
        Enum(SplitCandidateStatus),
        nullable=False,
        default=SplitCandidateStatus.pending,
    )
    # String, not Enum, so adding a future detector (e.g. "manual") doesn't
    # need a migration. Mirrors merge_candidates.detected_by convention.
    detected_by = Column(String(32), nullable=False)  # "scrape", "backfill", "merge_survivor"
    notes = Column(String, nullable=True)

    anime = relationship("Anime", foreign_keys=[anime_id], lazy="raise")

    __table_args__ = (
        # Admin list scans pending only; partial keeps the index tiny as
        # resolved rows accumulate. Mirrors merge_candidates.
        Index(
            "ix_split_candidates_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
