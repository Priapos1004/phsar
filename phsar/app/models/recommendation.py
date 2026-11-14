"""A user's stored recommendation ranking, the key it was computed for, and the stretches
each pick spent in the row — docs/features/recommender.md."""

import enum

from sqlalchemy import (
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import BaseModel, enum_values


class RecommendationKind(str, enum.Enum):
    """Why a pick is in the ranking (`recommender_compute.Pick.kind`)."""
    CONTINUE = "continue"
    WATCHLIST = "watchlist"
    FRESH = "fresh"
    RECENT = "recent"
    FAVOURITE = "favourite"
    POPULAR = "popular"
    EXPLORE = "explore"


_KIND = Enum(RecommendationKind, name="recommendation_kind", values_callable=enum_values)


class Recommendation(Base):
    """One anime in a user's ranking. On bare `Base` like `user_visible_media`: a cache
    deleted and rewritten whole on every recompute, so a uuid would name nothing for longer
    than one ranking and its timestamps would repeat the state row's. A pick as it was shown
    lives on in `RecommendationExposure`."""

    __tablename__ = "recommendations"

    # No index=True: the PK's own btree covers it (see BaseModel.id).
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    anime_id: Mapped[int] = mapped_column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[RecommendationKind] = mapped_column(_KIND, nullable=False)
    # The anime a recent or favourite reason names.
    ref_anime_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("anime.id", ondelete="SET NULL"), nullable=True)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "anime_id", name="uq_recommendations_user_anime"),)


class RecommendationState(BaseModel):
    """The inputs a user's stored ranking was computed from. Sidecar to `users`."""

    __tablename__ = "recommendation_state"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False,
    )
    inputs_key: Mapped[str] = mapped_column(String, nullable=False)


class RecommendationExposure(BaseModel):
    """One stretch an anime spent in a user's row: opened at `created_at`, last seen there at
    `modified_at`."""

    __tablename__ = "recommendation_exposure"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    anime_id: Mapped[int] = mapped_column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)
    best_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[RecommendationKind] = mapped_column(_KIND, nullable=False)


Index("ix_recommendation_exposure_user_anime", RecommendationExposure.user_id, RecommendationExposure.anime_id)
