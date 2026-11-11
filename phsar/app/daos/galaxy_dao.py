from collections import defaultdict
from itertools import batched
from typing import Any

from sqlalchemy import Float, Numeric, Row, cast, delete, distinct, func, insert, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, defer

from app.daos.base_dao import BaseDAO
from app.daos.search_filters import (
    MAIN_STORY,
    anime_genre_majority_relation,
    top_percent_ranking,
    weighted_mean_score_expr,
    weighted_mean_votes_expr,
)
from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.galaxy import GalaxyFit, GalaxyGroup, GalaxyStar
from app.models.genre import Genre
from app.models.media import AIRING_STATUS_FINISHED_AIRING, MAIN_STORY_RELATIONS, Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.services.galaxy_compute import AnimeRow, MediaRow


def _anime_figures(scope):
    """Per anime in `scope`: the relation-weighted MAL score rounded to two places, as the
    card rounds it, and its main story's first season year, most common source and most
    common format."""
    return (
        select(
            Media.anime_id.label("anime_id"),
            cast(func.round(cast(weighted_mean_score_expr(), Numeric), 2), Float).label("score"),
            func.min(Media.anime_season_year).filter(MAIN_STORY).label("year"),
            func.mode().within_group(Media.original_source).filter(MAIN_STORY).label("source"),
            func.mode().within_group(Media.media_type).filter(MAIN_STORY).label("format"),
        )
        .where(Media.anime_id.in_(scope))
        .group_by(Media.anime_id)
        .subquery()
    )


def _anime_genres(scope):
    """Per anime in `scope`, the genres the majority rule gives it, A→Z."""
    majority = anime_genre_majority_relation()
    return (
        select(
            majority.c.anime_id,
            func.array_agg(aggregate_order_by(majority.c.genre_name, majority.c.genre_name)).label("genres"),
        )
        .where(majority.c.anime_id.in_(scope))
        .group_by(majority.c.anime_id)
        .subquery()
    )


def _anime_studios(scope):
    """Per anime in `scope`, the studios behind its main story."""
    return (
        select(Media.anime_id.label("anime_id"), func.array_agg(distinct(Studio.name)).label("studios"))
        .join(MediaStudio, MediaStudio.media_id == Media.id)
        .join(Studio, Studio.id == MediaStudio.studio_id)
        .where(Media.anime_id.in_(scope), MAIN_STORY)
        .group_by(Media.anime_id)
        .subquery()
    )


def _card_columns(figures, genres) -> tuple:
    """What a map star and a neighbour both show of their anime."""
    return (
        Anime.uuid.label("anime_uuid"), Anime.title, Anime.name_eng, Anime.name_jap, Anime.cover_image,
        figures.c.score, figures.c.year, genres.c.genres,
    )


class GalaxyDAO(BaseDAO[GalaxyGroup]):
    def __init__(self):
        super().__init__(GalaxyGroup)

    async def catalogue_size(self, db: AsyncSession) -> int:
        """How many anime a fit would read: those with a description embedding."""
        return (await db.execute(select(func.count()).select_from(AnimeSearch))).scalar_one()

    async def load_catalogue(
        self, db: AsyncSession, anime_ids: list[int] | None = None,
    ) -> tuple[list[AnimeRow], list[MediaRow]]:
        """What `galaxy_compute` reads, as plain rows it can take into another process:
        every anime with a description embedding (or the given ones), and its media, with
        the app's own definitions resolved here — the compute side imports nothing from
        the app. Flat queries rather than eager-loaded ORM graphs: the fit reads a dozen
        scalars per media and nothing else."""
        in_catalogue = Media.anime_id.in_(select(AnimeSearch.anime_id) if anime_ids is None else anime_ids)
        scores = {
            aid: (score, votes) for aid, score, votes in (await db.execute(
                select(Media.anime_id, weighted_mean_score_expr(), weighted_mean_votes_expr())
                .where(in_catalogue).group_by(Media.anime_id)
            )).all()
        }
        anime_stmt = (
            select(AnimeSearch.anime_id, AnimeSearch.description_embedding, func.length(func.coalesce(Anime.description, "")))
            .join(Anime, Anime.id == AnimeSearch.anime_id)
            .order_by(AnimeSearch.anime_id)
        )
        if anime_ids is not None:
            anime_stmt = anime_stmt.where(AnimeSearch.anime_id.in_(anime_ids))
        anime = [
            AnimeRow(aid, vec.tolist(), *scores.get(aid, (None, None)), synopsis=chars)
            for aid, vec, chars in (await db.execute(anime_stmt)).all()
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
        `galaxy_compute.carry_names`: sectors first, then by number, so a tie in its greedy
        match and the order of the names it drops are the same on every run."""
        groups = (await db.execute(
            select(GalaxyGroup.id, GalaxyGroup.parent_id, GalaxyGroup.name)
            .where(GalaxyGroup.name.is_not(None))
            .order_by(GalaxyGroup.parent_id.is_not(None), GalaxyGroup.number)
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

    async def live_models(self, db: AsyncSession) -> Row | None:
        """The live fit's id, params and pickled models, for placing anime onto it."""
        return (await db.execute(select(GalaxyFit.id, GalaxyFit.params, GalaxyFit.models))).one_or_none()

    async def unplaced_anime_ids(self, db: AsyncSession) -> list[int]:
        """Anime a fit would read that have no star yet."""
        return list((await db.execute(
            select(AnimeSearch.anime_id)
            .outerjoin(GalaxyStar, GalaxyStar.anime_id == AnimeSearch.anime_id)
            .where(GalaxyStar.id.is_(None))
        )).scalars())

    async def add_stars(self, db: AsyncSession, fit_id: int, stars: list[dict[str, Any]]) -> None:
        """Place stars onto the fit they were predicted from."""
        ids = {
            ("sector" if parent_id is None else "region", number): gid
            for gid, number, parent_id in (await db.execute(
                select(GalaxyGroup.id, GalaxyGroup.number, GalaxyGroup.parent_id).where(GalaxyGroup.fit_id == fit_id)
            )).all()
        }
        await self._insert_stars(db, ids, stars)

    async def map_groups(self, db: AsyncSession) -> list[Row]:
        """The live map's sectors and regions, each named by its hand name or else its auto name;
        a region carries its sector's number."""
        parent = aliased(GalaxyGroup)
        return list((await db.execute(
            select(
                GalaxyGroup.uuid, GalaxyGroup.number, GalaxyGroup.x, GalaxyGroup.y,
                func.coalesce(GalaxyGroup.name, GalaxyGroup.auto_name).label("name"),
                parent.number.label("sector"),
            )
            .outerjoin(parent, parent.id == GalaxyGroup.parent_id)
            .order_by(GalaxyGroup.number)
        )).all())

    async def map_stars(self, db: AsyncSession) -> list[Row]:
        """Every star with what the map shows of its anime. One flat query: the payload is
        the whole catalogue."""
        placed = select(GalaxyStar.anime_id)
        figures, genres = _anime_figures(placed), _anime_genres(placed)
        top = top_percent_ranking(per_anime=True)
        sector, region = aliased(GalaxyGroup), aliased(GalaxyGroup)
        return list((await db.execute(
            select(
                *_card_columns(figures, genres), top.c.top_percent,
                GalaxyStar.x, GalaxyStar.y, GalaxyStar.between, GalaxyStar.trained,
                sector.number.label("sector"), region.number.label("region"),
            )
            .join(GalaxyStar, GalaxyStar.anime_id == Anime.id)
            .join(sector, sector.id == GalaxyStar.sector_id)
            .join(region, region.id == GalaxyStar.region_id)
            .outerjoin(figures, figures.c.anime_id == Anime.id)
            .outerjoin(genres, genres.c.anime_id == Anime.id)
            .outerjoin(top, top.c.id == Anime.id)
            .order_by(GalaxyStar.id)
        )).all())

    async def star_features(self, db: AsyncSession, anime_uuid) -> Row | None:
        """An anime's id and feature vector, when it has a star."""
        return (await db.execute(
            select(GalaxyStar.anime_id, GalaxyStar.features)
            .join(Anime, Anime.id == GalaxyStar.anime_id)
            .where(Anime.uuid == anime_uuid)
        )).one_or_none()

    async def nearest(self, db: AsyncSession, anime_id: int, features, limit: int) -> list[int]:
        """The anime whose stars sit nearest, nearest first, by `galaxy_compute.distances`
        less the asking star's own uncertainty, the same for every row. No index: a
        catalogue-sized scan is cheap, an approximate index would reorder close ties, and
        none indexes the sum."""
        return list((await db.execute(
            select(GalaxyStar.anime_id)
            .where(GalaxyStar.anime_id != anime_id)
            .order_by(func.power(GalaxyStar.features.l2_distance(features), 2) + GalaxyStar.uncertainty, GalaxyStar.anime_id)
            .limit(limit)
        )).scalars())

    async def trait_counts(self, db: AsyncSession) -> tuple[int, dict[tuple[str, str], int]]:
        """How many anime the map holds, and how many of them carry each trait `anime_facts`
        compares, keyed `(kind, name)` by the same definitions, so a shared trait's count is
        that trait's."""
        placed = select(GalaxyStar.anime_id)
        majority, figures = anime_genre_majority_relation(), _anime_figures(placed)
        total = (await db.execute(select(func.count()).select_from(GalaxyStar))).scalar_one()
        genres = select(majority.c.genre_name, func.count()).where(majority.c.anime_id.in_(placed)).group_by(majority.c.genre_name)
        named = select(func.unnest(_anime_studios(placed).c.studios).label("name")).subquery()
        studios = select(named.c.name, func.count()).group_by(named.c.name)
        # Source and format in one query, so `_anime_figures` runs once.
        both = select(figures.c.source, figures.c.format, func.count()).group_by(figures.c.source, figures.c.format)
        counts: dict[tuple[str, str], int] = defaultdict(int)
        counts |= {("genre", name): n for name, n in (await db.execute(genres)).tuples()}
        counts |= {("studio", name): n for name, n in (await db.execute(studios)).tuples()}
        for source, fmt, n in (await db.execute(both)).tuples():
            for kind, value in (("source", source), ("format", fmt)):
                if value is not None:
                    counts[(kind, value.value)] += n
        return total, dict(counts)

    async def anime_facts(self, db: AsyncSession, anime_ids: list[int]) -> dict[int, Row]:
        """What the neighbour reasons compare, per anime."""
        figures, genres, studios = _anime_figures(anime_ids), _anime_genres(anime_ids), _anime_studios(anime_ids)
        rows = (await db.execute(
            select(
                Anime.id, *_card_columns(figures, genres),
                figures.c.source, figures.c.format, studios.c.studios, AnimeSearch.description_embedding,
                (func.coalesce(Anime.description, "") != "").label("has_synopsis"),
            )
            .join(AnimeSearch, AnimeSearch.anime_id == Anime.id)
            .outerjoin(figures, figures.c.anime_id == Anime.id)
            .outerjoin(genres, genres.c.anime_id == Anime.id)
            .outerjoin(studios, studios.c.anime_id == Anime.id)
            .where(Anime.id.in_(anime_ids))
        )).all()
        return {row.id: row for row in rows}

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
        await self._insert_stars(db, ids, stars)

    @staticmethod
    async def _insert_stars(db: AsyncSession, ids: dict[tuple[str, int], int], stars: list[dict[str, Any]]) -> None:
        """Stars as `galaxy_compute` answers them, their sector and region numbers resolved
        to the fit's group ids."""
        # In chunks: pgvector writes each vector out as text on the event loop, in time that
        # grows with the catalogue, and a chunk at a time lets requests run between.
        # Never an empty one, which would fall back to a single insert of defaults.
        for chunk in batched(stars, 200):
            await db.execute(insert(GalaxyStar), [
                {
                    "anime_id": s["anime_id"], "x": s["x"], "y": s["y"], "z10": s["z10"],
                    "features": s["features"], "uncertainty": s["uncertainty"], "between": s["between"], "trained": s["trained"],
                    "sector_id": ids[("sector", s["sector"])], "region_id": ids[("region", s["region"])],
                }
                for s in chunk
            ])
