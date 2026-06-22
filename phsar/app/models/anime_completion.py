"""Admin-curated "story complete" flag for an anime (v0.14.10).

1:1 sidecar to `anime`: the row's *presence* means an admin has marked the
anime's narrative as concluded — distinct from MAL's broadcast `airing_status`
("Finished Airing" only means episodes stopped airing, not that the story is
done; an announced-but-unaired sequel, or an ongoing manga adaptation, is
"Finished Airing" yet not story-complete).

Row-presence (not a boolean column) is the flag: marking inserts, unmarking
deletes — so the admin list is a plain `SELECT * FROM anime_completion` with no
"row exists but is_finished=false" ambiguity. `marked_by_user_id` + `created_at`
(BaseModel) are the audit trail of who/when.

Operational/admin state lives off the canonical `anime` row (sidecar convention,
like anime_freshness) so it can't leak into the anime Pydantic schemas via
`model_dump()`; the detail endpoint surfaces it explicitly as `is_finished`.

Future: a user-report → admin-approve flow can add columns here without
restructuring (tracked on GH issue #58).
"""

from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AnimeCompletion(BaseModel):
    __tablename__ = "anime_completion"

    anime_id = Column(
        Integer,
        ForeignKey("anime.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Who marked it. SET NULL (not CASCADE) so deleting the admin account doesn't
    # un-mark the anime — the completion fact outlives its author.
    marked_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    anime = relationship("Anime", back_populates="completion", lazy="raise")
    # One-directional (no back-ref on Users): read the marker's username for the
    # admin Completion list's audit line. Explicit foreign_keys since Users has no
    # back_populates here.
    marked_by = relationship("Users", foreign_keys=[marked_by_user_id], lazy="raise")
