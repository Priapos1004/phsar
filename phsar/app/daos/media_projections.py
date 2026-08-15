"""Shared column blocks for the wide per-user list projections.

`/ratings/scores` and `/watchlist/items` both build DTOs of scalars plus a
media's genre and studio names. Fetching those through `selectinload` costs a
round trip each plus full ORM hydration of the M2M rows and their targets, for
values only ever read as flat lists of strings — so both endpoints select them
here instead, as one flat statement.

Shared from this module rather than duplicated per DAO for two reasons: the two
endpoints must agree on array ordering, and the identity columns below are
load-bearing in a way that fails silently (see `media_identity_columns`).
"""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.models.anime import Anime
from app.models.genre import Genre
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio


def media_identity_columns():
    """Media's five identity columns, labelled `media_*`.

    The labels are not decoration: `uuid`, `title`, `name_eng`, `name_jap` and
    `cover_image` all exist on Anime too, so an unlabelled projection selecting
    both silently collapses each pair. Shared so the two grains can't drift into
    different label spellings.
    """
    return (
        Media.uuid.label("media_uuid"),
        Media.title.label("media_title"),
        Media.name_eng.label("media_name_eng"),
        Media.name_jap.label("media_name_jap"),
        Media.cover_image.label("media_cover_image"),
    )


def anime_identity_columns():
    """Anime's five identity columns, labelled `anime_*` — the other half of the
    colliding pair described in `media_identity_columns`."""
    return (
        Anime.uuid.label("anime_uuid"),
        Anime.title.label("anime_title"),
        Anime.name_eng.label("anime_name_eng"),
        Anime.name_jap.label("anime_name_jap"),
        Anime.cover_image.label("anime_cover_image"),
    )


def _name_agg(join_model, name_model, join_fk, media_id_scope, label: str):
    """Per-media aggregated names for a BOUNDED set of media, as a subquery to
    LEFT JOIN on `media_id`.

    The scope is the whole point. Written as a correlated `array_agg` per row
    instead, Postgres evaluates one subplan per output row — an index scan plus a
    tiny sort each, ~900 of them for a 456-row page — and the cost scales with
    the page. Grouped once over the *whole* catalogue is worse again (it
    aggregates ~18k rows nobody asked for). Grouped once over just this user's
    media is the cheap form: two index scans, flat in row count.

    Ordered by name so the output is deterministic — physical row order isn't
    stable across a re-scrape or a VACUUM, and a list whose order wobbles
    between responses is a diffing hazard for consumers.

    A media with no rows here simply has no subquery row, so the LEFT JOIN
    yields SQL NULL rather than an empty array; callers normalize with `or []`.
    """
    return (
        select(
            join_model.media_id.label("media_id"),
            func.array_agg(
                aggregate_order_by(name_model.name, name_model.name)
            ).label(label),
        )
        .join(name_model, join_fk == name_model.id)
        .where(join_model.media_id.in_(media_id_scope))
        .group_by(join_model.media_id)
        .subquery()
    )


def media_genre_names(media_id_scope):
    """Genre names per media, scoped to `media_id_scope`. See `_name_agg`."""
    return _name_agg(MediaGenre, Genre, MediaGenre.genre_id, media_id_scope, "genres")


def media_studio_names(media_id_scope):
    """Studio names per media, scoped to `media_id_scope`. See `_name_agg`."""
    return _name_agg(MediaStudio, Studio, MediaStudio.studio_id, media_id_scope, "studios")
