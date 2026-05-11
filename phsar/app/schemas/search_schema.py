from pydantic import BaseModel, Field

from app.schemas.media_schema import MediaUnconnected


class SearchResultDB(BaseModel):
    anime_mal_id: int
    unconnected_media_list: list[MediaUnconnected]
    # mal_ids the BFS would have traversed but skipped because the media
    # already exists in our catalog under some other anime, reached via a
    # non-crossover relation. Resolved to anime ids in save_service and
    # turned into relation_link merge candidates.
    cross_link_mal_ids: set[int] = Field(default_factory=set)


class AttachToExistingAction(BaseModel):
    """A BFS graph that has no `main` relation but cross-links to exactly
    one existing anime in the catalog (typical case: seasonal sweep
    surfaces a side-story whose parent show is already in the DB).
    The caller looks up the parent Anime by `target_mal_id` (one of its
    existing Media mal_ids) and feeds `related_anime_graph` + `all_info`
    straight into `attach_search_result_to_anime`, the same primitive
    the 7c relations probe uses."""
    target_mal_id: int
    related_anime_graph: dict
    all_info: dict


class SearchResultDBExtended(BaseModel):
    search_result_db_list: list[SearchResultDB]
    unwanted_media: set[tuple[int, str, str]]
    # Orphan-side-story graphs that resolve cleanly to a single existing
    # parent. Empty for the common path; populated when MAL surfaces a
    # side-story whose parent show is already in our catalog. The dispatcher
    # (and only the dispatcher — not the public /search/mal route) acts on
    # these by attaching the new media under the existing parent.
    attach_actions: list[AttachToExistingAction] = Field(default_factory=list)
