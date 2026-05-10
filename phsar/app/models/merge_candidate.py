import enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MergeCandidateStatus(str, enum.Enum):
    pending = "pending"
    dismissed = "dismissed"
    merged = "merged"


class MergeCandidate(BaseModel):
    __tablename__ = "merge_candidates"

    # Detector is responsible for ordering: anime_a_id < anime_b_id so the
    # unique constraint collapses (A,B) and (B,A) into one row.
    anime_a_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)
    anime_b_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)

    similarity_score = Column(Float, nullable=False)

    # String, not Enum, so adding a future detector ('description_overlap',
    # 'shared_mal_id', ...) doesn't need a migration.
    detected_by = Column(String(32), nullable=False)
    status = Column(
        Enum(MergeCandidateStatus),
        nullable=False,
        default=MergeCandidateStatus.pending,
    )
    notes = Column(String, nullable=True)

    anime_a = relationship("Anime", foreign_keys=[anime_a_id], lazy="raise")
    anime_b = relationship("Anime", foreign_keys=[anime_b_id], lazy="raise")

    __table_args__ = (
        UniqueConstraint("anime_a_id", "anime_b_id", name="uq_merge_candidates_pair"),
        CheckConstraint("anime_a_id < anime_b_id", name="ck_merge_candidates_pair_ordered"),
        # Admin list scans pending only; partial keeps it tiny as resolved
        # rows accumulate.
        Index(
            "ix_merge_candidates_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
