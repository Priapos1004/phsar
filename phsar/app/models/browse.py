"""Carousel definitions for the browse pages: carousels, the filter sets they offer,
and the links between them (docs/features/browse.md)."""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class BrowseCarousel(BaseModel):
    __tablename__ = "browse_carousel"

    # Stable identifier; the browse URLs carry it.
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    see_all_limit: Mapped[int] = mapped_column(Integer, nullable=False)

    filter_sets: Mapped[list["CarouselFilterSet"]] = relationship(
        order_by="CarouselFilterSet.position",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )


class BrowseFilterSet(BaseModel):
    __tablename__ = "browse_filter_set"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class CarouselFilterSet(BaseModel):
    __tablename__ = "carousel_filter_set"

    carousel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("browse_carousel.id", ondelete="CASCADE"), nullable=False,
    )
    filter_set_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("browse_filter_set.id", ondelete="CASCADE"), nullable=False,
    )
    default_on: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The resolver's merge order (docs/features/browse.md).
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    filter_set: Mapped["BrowseFilterSet"] = relationship(lazy="raise")

    __table_args__ = (
        # Also the carousel_id lookup's index, as its leading column.
        UniqueConstraint("carousel_id", "filter_set_id", name="uq_carousel_filter_set"),
    )
