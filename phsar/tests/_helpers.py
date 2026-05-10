"""Shared test helpers across services/, routers/, daos/.

`media_kwargs` filled out four times in test files because every test that
touches a Media row has to populate the same NOT-NULL columns. This is the
canonical version; new tests should import it instead of redeclaring.
"""

from app.models.media import MediaType, RelationType


def media_kwargs(anime_id: int, mal_id: int, **overrides) -> dict:
    """Return a dict suitable for `Media(**...)` with all NOT-NULL columns
    populated. Pass keyword overrides to customize specific fields."""
    base = dict(
        anime_id=anime_id,
        mal_id=mal_id,
        mal_url=f"https://example/{mal_id}",
        title=f"M{mal_id}",
        media_type=MediaType.TV,
        relation_type=RelationType.Main,
        scored_by=0,
        airing_status="Finished Airing",
    )
    base.update(overrides)
    return base
