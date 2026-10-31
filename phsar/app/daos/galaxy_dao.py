from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.daos.base_dao import BaseDAO
from app.daos.search_filters import weighted_mean_score_expr, weighted_mean_votes_expr
from app.models.anime_search import AnimeSearch
from app.models.galaxy import GalaxyFit, GalaxyGroup, GalaxyStar
from app.models.genre import Genre
from app.models.media import AIRING_STATUS_FINISHED_AIRING, MAIN_STORY_RELATIONS, Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.services.galaxy_compute import AnimeRow, MediaRow


class GalaxyDAO(BaseDAO[GalaxyGroup]):
    def __init__(self):
        super().__init__(GalaxyGroup)

    async def catalogue_size(self, db: AsyncSession) -> int:
        """How many anime a fit would read: those with a description embedding."""
        return (await db.execute(select(func.count()).select_from(AnimeSearch))).scalar_one()

    async def load_catalogue(self, db: AsyncSession) -> tuple[list[AnimeRow], list[MediaRow]]:
        """What `galaxy_compute` reads, as plain rows it can take into another process:
        every anime with a description embedding, and its media, with the app's own
        definitions resolved here — the compute side imports nothing from the app.
        Flat queries rather than eager-loaded ORM graphs: the fit reads a dozen scalars
        per media and nothing else."""
        in_catalogue = Media.anime_id.in_(select(AnimeSearch.anime_id))
        scores = {
            aid: (score, votes) for aid, score, votes in (await db.execute(
                select(Media.anime_id, weighted_mean_score_expr(), weighted_mean_votes_expr())
                .where(in_catalogue).group_by(Media.anime_id)
            )).all()
        }
        anime = [
            AnimeRow(aid, [float(v) for v in vec], *scores.get(aid, (None, None)))
            for aid, vec in (await db.execute(
                select(AnimeSearch.anime_id, AnimeSearch.description_embedding).order_by(AnimeSearch.anime_id)
            )).all()
        ]

        media = (await db.execute(
            select(
                Media.id, Media.anime_id, Media.relation_type, Media.airing_status, Media.score,
                Media.media_type, Media.age_rating_numeric, Media.original_source,
                Media.total_watch_time, Media.anime_season_year,
            ).where(in_catalogue)
        )).all()
        tags: dict[int, list[tuple[str, str]]] = defaultdict(list)
        for media_id, name, kind in (await db.execute(
            select(MediaGenre.media_id, Genre.name, Genre.genre_type)
            .join(Genre, Genre.id == MediaGenre.genre_id)
            .join(Media, Media.id == MediaGenre.media_id)
            .where(in_catalogue)
        )).all():
            tags[media_id].append((name, kind.value))
        studios: dict[int, list[str]] = defaultdict(list)
        for media_id, name in (await db.execute(
            select(MediaStudio.media_id, Studio.name)
            .join(Studio, Studio.id == MediaStudio.studio_id)
            .join(Media, Media.id == MediaStudio.media_id)
            .where(in_catalogue)
        )).all():
            studios[media_id].append(name)

        return anime, [
            MediaRow(
                anime_id=m.anime_id, main=m.relation_type in MAIN_STORY_RELATIONS,
                settled=m.airing_status == AIRING_STATUS_FINISHED_AIRING and m.score is not None,
                media_type=m.media_type.value, age=m.age_rating_numeric,
                source=m.original_source.value if m.original_source else None,
                watch_seconds=m.total_watch_time, season_year=m.anime_season_year,
                tags=tuple(tags[m.id]), studios=tuple(studios[m.id]),
            )
            for m in media
        ]

    async def previous_layout(self, db: AsyncSession) -> dict[int, tuple[list[float], list[float]]]:
        """Each placed anime's (2-D, 10-D) coordinates — where a refit starts from."""
        rows = (await db.execute(select(GalaxyStar.anime_id, GalaxyStar.x, GalaxyStar.y, GalaxyStar.z10))).all()
        return {aid: ([x, y], [float(v) for v in z10]) for aid, x, y, z10 in rows}

    async def named_groups(self, db: AsyncSession) -> list[tuple[str, frozenset[int], str]]:
        """The live map's hand-named groups with their trained members, for
        `galaxy_compute.carry_names`."""
        groups = (await db.execute(
            select(GalaxyGroup.id, GalaxyGroup.parent_id, GalaxyGroup.name).where(GalaxyGroup.name.is_not(None))
        )).all()
        if not groups:
            return []
        members: dict[int, set[int]] = defaultdict(set)
        for anime_id, sector_id, region_id in (await db.execute(
            select(GalaxyStar.anime_id, GalaxyStar.sector_id, GalaxyStar.region_id).where(GalaxyStar.trained)
        )).all():
            members[sector_id].add(anime_id)
            members[region_id].add(anime_id)
        return [
            ("sector" if parent_id is None else "region", frozenset(members[gid]), name)
            for gid, parent_id, name in groups
        ]

    async def live_fit(self, db: AsyncSession) -> GalaxyFit | None:
        """The live fit's metadata; its pickled models stay in the database."""
        return (await db.execute(
            select(GalaxyFit).options(defer(GalaxyFit.models, raiseload=True))
        )).scalar_one_or_none()

    async def replace_fit(
        self, db: AsyncSession, *, blob: bytes, params: dict[str, Any],
        groups: list[dict[str, Any]], names: dict[int, str], stars: list[dict[str, Any]],
    ) -> None:
        """Swap the live map for a new one. The old fit's delete cascades through its
        groups and stars in the database, so the caller's one commit is the swap:
        readers see the old map or the new one, never a mix."""
        await db.execute(delete(GalaxyFit))
        fit = GalaxyFit(models=blob, params=params)
        db.add(fit)
        await db.flush()
        ids: dict[tuple[str, int], int] = {}
        # Sectors first, so a region's parent has an id.
        for index, g in sorted(enumerate(groups), key=lambda ig: ig[1]["level"] != "sector"):
            row = GalaxyGroup(
                fit_id=fit.id, number=g["number"], name=names.get(index), auto_name=g["auto_name"],
                x=g["x"], y=g["y"],
                parent_id=None if g["parent"] is None else ids[("sector", g["parent"])],
            )
            db.add(row)
            await db.flush()
            ids[(g["level"], g["number"])] = row.id
        if not stars:
            # An empty executemany falls back to a single insert of defaults.
            return
        await db.execute(insert(GalaxyStar), [
            {
                "anime_id": s["anime_id"], "x": s["x"], "y": s["y"], "z10": s["z10"],
                "features": s["features"], "between": s["between"], "trained": s["trained"],
                "sector_id": ids[("sector", s["sector"])], "region_id": ids[("region", s["region"])],
            }
            for s in stars
        ])
