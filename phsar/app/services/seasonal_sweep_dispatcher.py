"""Weekly seasonal sweep — paginates /seasons/now and enqueues child
user_scrape jobs for any mal_id the catalog doesn't already know about.

Lives in its own module rather than alongside user_scrape / update_sweep
because it shares no helpers with them: the seasonal sweep does no
per-anime field diff, no relations BFS, no stability accounting. It is
purely a discovery pass that hands off work to the existing user_scrape
pipeline.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.job_versions import make_job
from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.models.job import Job, JobKind, JobStatus
from app.services.jikan_scraper import JikanScraper
from app.services.job_worker import job_worker
from app.services.progress_reporter import ProgressReporter

logger = logging.getLogger(__name__)


async def seasonal_sweep_dispatcher(session: AsyncSession, job: Job) -> dict:
    """Weekly: paginate /seasons/now, dedupe against the catalog
    (`Anime.mal_id ∪ Media.mal_id ∪ MediaUnwanted.mal_id`), and enqueue
    one `user_scrape` job per new mal_id. Children carry the seed mal_id
    so the BFS skips the fuzzy q= lookup that would otherwise pull
    unrelated top-3 matches into the catalog.

    Per-row commit mirrors update_sweep's per-anime pattern from 7b: if
    the loop dies mid-batch, already-enqueued children survive. Children
    are `requested_by_user_id=None` (system jobs) — they skip the
    per-user submission cap and don't surface in any user's bell. The
    dispatcher itself completes in seconds (single MAL fetch + N row
    inserts); the long tail of child user_scrapes runs after the
    maintenance flag flips off, which is safe because additive scrapes
    don't disrupt live traffic.
    """
    progress = ProgressReporter(job.id)
    await progress.update(stage="Fetching season", force=True)

    async with JikanScraper() as scraper:
        entries = await scraper.fetch_current_season()

    # Three sequential reads — SQLAlchemy's AsyncSession isn't safe for
    # concurrent operations on a single session, so asyncio.gather() here
    # would corrupt the connection state. Three round-trips is fine in
    # exchange for one shared session.
    anime_ids = await AnimeDAO().get_all_mal_ids(session)
    media_ids = await MediaDAO().get_all_mal_ids(session)
    unwanted_ids = await MediaUnwantedDAO().get_all_mal_ids(session)
    # Media.mal_id is included because a season entry may already exist
    # as a side-story under a parent anime — we'd otherwise re-scrape
    # the same show from a different angle and trip the merge detector.
    # `seen` starts seeded with the catalog so the same pass dedupes
    # both against the DB *and* against duplicates within `entries`
    # itself: MAL's /seasons/now has been observed to repeat a mal_id
    # across pages, and without per-run dedupe each duplicate enqueues
    # its own child user_scrape (and they all fail the same way).
    seen: set[int] = set(anime_ids) | set(media_ids) | set(unwanted_ids)
    new_entries: list[dict] = []
    for entry in entries:
        mal_id = entry.get("mal_id")
        if mal_id is None or mal_id in seen:
            continue
        new_entries.append(entry)
        seen.add(mal_id)
    await progress.update(
        stage="Enqueuing",
        items_total=len(new_entries),
        items_done=0,
        force=True,
    )

    # Bulk insert + single commit. The enqueue loop does no MAL I/O
    # (already drained in the season-fetch step above), so the
    # per-anime commit pattern that update_sweep uses for crash-safety
    # would just extend the maintenance window without any work to
    # preserve — a crash here loses nothing the next scheduled run
    # can't reproduce by re-querying /seasons/now.
    children = [
        make_job(
            JobKind.user_scrape,
            status=JobStatus.queued,
            requested_by_user_id=None,
            # Stamp the parent so the admin Jobs Log can collapse this flock
            # under the seasonal_sweep row instead of cluttering the default
            # view with N system-attributed scrapes per Sunday.
            parent_job_id=job.id,
            payload={"query": entry.get("title") or f"mal_id={entry['mal_id']}", "mal_id": entry["mal_id"]},
        )
        for entry in new_entries
    ]
    if children:
        session.add_all(children)
        await session.commit()
        # Single notify after the commit — the worker picks the first
        # child immediately instead of waiting up to 60s for the
        # wall-clock fallback.
        job_worker.notify()

    enqueued = len(children)
    await progress.update(stage="Done", items_done=enqueued, force=True)
    return {
        "season_entries": len(entries),
        "new_entries_enqueued": enqueued,
        "dedup_skipped": len(entries) - enqueued,
    }
