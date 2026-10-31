"""The galaxy map: one live fit, its named sectors and regions, and a star per anime.
Everything below a fit cascades from it (`GalaxyDAO.replace_fit`); how a fit is made:
docs/features/galaxy.md.
"""

from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.anime import Anime


class GalaxyFit(BaseModel):
    __tablename__ = "galaxy_fits"

    # The fitted models and the training statistics placement needs, pickled. Only
    # `galaxy_compute` reads it back, in its own process.
    models: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # What it was built from (`galaxy_service.built_from`), the job's summary, and the
    # synopsis-similarity percentiles of random pairs.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class GalaxyGroup(BaseModel):
    """A sector (no parent) or one of its regions."""

    __tablename__ = "galaxy_groups"

    fit_id: Mapped[int] = mapped_column(Integer, ForeignKey("galaxy_fits.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("galaxy_groups.id", ondelete="CASCADE"), nullable=True,
    )
    # The fit's own label for the group; placement answers in these.
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # A hand name, carried onto each refit by member overlap; the auto name shows without one.
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_name: Mapped[str] = mapped_column(String, nullable=False)
    # Where the label sits: the members' mean position.
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)


class GalaxyStar(BaseModel):
    """One anime's place on the map. Sidecar to `anime` (`.claude/rules/database.md`): an
    anime without a row is not placed yet."""

    __tablename__ = "galaxy_stars"

    anime_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("anime.id", ondelete="CASCADE"), unique=True, nullable=False,
    )
    sector_id: Mapped[int] = mapped_column(Integer, ForeignKey("galaxy_groups.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[int] = mapped_column(Integer, ForeignKey("galaxy_groups.id", ondelete="CASCADE"), nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    # The 10-D layout the sectors are found in; a refit starts from it.
    z10: Mapped[Any] = mapped_column(Vector(10), nullable=False)
    # The weighted feature vector the fit clustered. No fixed dimension: the blocks are
    # as wide as the fit's tag and studio catalogue.
    features: Mapped[Any] = mapped_column(Vector(), nullable=False)
    # HDBSCAN called it noise: it keeps its likeliest sector but draws between regions.
    between: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Fitted from (a settled anime) rather than placed onto the map.
    trained: Mapped[bool] = mapped_column(Boolean, nullable=False)

    anime: Mapped["Anime"] = relationship("Anime", back_populates="galaxy_star", lazy="raise")
