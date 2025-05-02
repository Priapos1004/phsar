from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.models.genre import Genre
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.services.vector_embedding_service import generate_embedding


class MediaDAO(MalIdDAO[Media]):
    def __init__(self):
        super().__init__(Media)

    async def search_media_by_vector_with_filters(
        self,
        db: AsyncSession,
        query: str,
        filters: MediaSearchFilters,
        search_type: SearchType,
        limit: int = 50,
    ) -> list[Media]:
        if query != "":
            query_embedding = await generate_embedding(query)

        # If filtering by genres (HAS AT LEAST ALL), use subquery
        if filters.genre_name:
            unique_genres = set(filters.genre_name)
            subquery = (
                select(Media.id)
                .join(Media.media_genre)
                .join(MediaGenre.genre)
                .where(Genre.name.in_(unique_genres))
                .group_by(Media.id)
                .having(func.count(distinct(Genre.id)) >= len(unique_genres))
            ).subquery()

            stmt = select(Media).join(MediaSearch).where(Media.id.in_(select(subquery.c.id)))
        else:
            stmt = select(Media).join(MediaSearch)

        # Apply eager loading
        stmt = stmt.options(
            selectinload(Media.media_genre).selectinload(MediaGenre.genre),
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
            selectinload(Media.anime),
        )

        # Studio filter
        if filters.studio_name:
            stmt = (
                stmt
                .join(Media.media_studio)
                .join(MediaStudio.studio)
                .where(Studio.name.in_(filters.studio_name))
            )

        # Other filters
        conditions = []

        if filters.media_type:
            conditions.append(Media.media_type.in_(filters.media_type))
        if filters.relation_type:
            conditions.append(Media.relation_type.in_(filters.relation_type))
        if filters.fsk:
            conditions.append(Media.fsk.in_(filters.fsk))
        if filters.airing_status:
            conditions.append(Media.airing_status.in_(filters.airing_status))
        if filters.anime_season:
            conditions.append(Media.anime_season.in_(filters.anime_season))

        if filters.score_min is not None:
            conditions.append((Media.score != None) & (Media.score >= filters.score_min))
        if filters.score_max is not None:
            conditions.append((Media.score != None) & (Media.score <= filters.score_max))
        if filters.scored_by_min is not None:
            conditions.append((Media.scored_by != None) & (Media.scored_by >= filters.scored_by_min))
        if filters.episodes_min is not None:
            conditions.append((Media.episodes != None) & (Media.episodes >= filters.episodes_min))
        if filters.episodes_max is not None:
            conditions.append((Media.episodes != None) & (Media.episodes <= filters.episodes_max))
        if filters.duration_per_episode_min is not None:
            conditions.append(
                (Media.duration_seconds != None) & (Media.duration_seconds >= filters.duration_per_episode_min)
            )
        if filters.duration_per_episode_max is not None:
            conditions.append(
                (Media.duration_seconds != None) & (Media.duration_seconds <= filters.duration_per_episode_max)
            )
        if filters.total_watch_time_min is not None:
            conditions.append(
                (Media.total_watch_time != None) & (Media.total_watch_time >= filters.total_watch_time_min)
            )
        if filters.total_watch_time_max is not None:
            conditions.append(
                (Media.total_watch_time != None) & (Media.total_watch_time <= filters.total_watch_time_max)
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        if query != "":
            if search_type == SearchType.TITLE:
                stmt = stmt.order_by(
                    func.cosine_distance(MediaSearch.title_embedding, cast(query_embedding, Vector))
                ).limit(limit)
            elif search_type == SearchType.DESCRIPTION:
                stmt = stmt.order_by(
                    func.cosine_distance(MediaSearch.description_embedding, cast(query_embedding, Vector))
                ).limit(limit)
        else:
            weighted_score = Media.score * func.log(Media.scored_by + 1)
            stmt = stmt.order_by(
                weighted_score
                .desc()
                .nullslast()
            ).limit(limit)

        results = (await db.execute(stmt)).scalars().all()
        return results
