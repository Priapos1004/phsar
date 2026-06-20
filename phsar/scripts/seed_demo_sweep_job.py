"""Seed a realistic demo `update_sweep` job for visually evaluating the
admin job-detail page (`/admin/jobs/[uuid]`) and the Jobs Log without
waiting for a real nightly sweep.

Builds a v6 `result_summary` populated from REAL catalog rows (so every
anime/media link resolves) covering every surface the v0.14.9 changes
touched: the counters grid, the "Anime changes" + "Media changes" cards
(incl. genre/studio drift), the scrollable Failed-refresh / Failed-probe
lists (~10 failures), the new "Attached via probe" card (Tensei Slime +
siblings), the progress-divergence notice, and the Jobs Log amber
(unknown-genre-tags) + blue (probe-attach) row tints.

Dry-runs by default; pass --apply to insert. `--delete` removes any
previously-seeded demo job (matched on the payload marker) so re-running
stays idempotent.

Usage:
    cd phsar
    python -m scripts.seed_demo_sweep_job            # dry-run (prints plan)
    python -m scripts.seed_demo_sweep_job --apply     # insert the demo job
    python -m scripts.seed_demo_sweep_job --delete --apply   # remove it
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.db import async_session_maker
from app.core.job_versions import make_job
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus

# Payload marker so --delete can find exactly the rows this script seeded
# (and never a real sweep, which has an empty payload).
_DEMO_MARKER = "demo_sweep_job"


def _anime_ref(a: Anime) -> dict:
    return {
        "anime_uuid": str(a.uuid),
        "title": a.title,
        "anime_name_eng": a.name_eng,
        "anime_name_jap": a.name_jap,
    }


def _media_change(a: Anime, m, *, dynamic=None, static=None, genre_drift=None,
                  studio_drift=None) -> dict:
    return {
        "static": static or [],
        "dynamic": dynamic or [],
        "anime_id": a.id,
        "media_id": m.id,
        "anime_uuid": str(a.uuid),
        "media_uuid": str(m.uuid),
        "anime_title": a.title,
        "genre_drift": genre_drift,
        "media_title": m.title,
        "media_mal_id": m.mal_id,
        "studio_drift": studio_drift,
        "anime_name_eng": a.name_eng,
        "anime_name_jap": a.name_jap,
        "media_name_eng": m.name_eng,
        "media_name_jap": m.name_jap,
        "media_relation_type": m.relation_type.value if m.relation_type else "main",
    }


def _build_summary(animes: list[Anime], *, include_genre_tags: bool = True) -> dict:
    """Compose a v6 result_summary from real catalog rows. `animes` is a
    pool of anime (media eager-loaded); roles are sliced off it so every
    uuid links to a live page.

    `include_genre_tags=False` drops the unknown-genre-tag drift entirely so
    the Jobs Log row gets NO amber tint — letting the blue probe-attach tint
    (which amber otherwise outranks) show in isolation."""
    # --- probe attachments: Tensei Slime (if present) + two siblings ---
    slime = next((a for a in animes if a.mal_id == 37430), None)
    attach_pool = [a for a in animes if a.media][:6]
    if slime and slime not in attach_pool[:3]:
        attach_pool = [slime, *[a for a in attach_pool if a is not slime]]
    probe_attached_anime = []
    for a in attach_pool[:3]:
        media = [
            {"media_uuid": str(m.uuid), "title": m.title,
             "name_eng": m.name_eng, "name_jap": m.name_jap}
            for m in a.media[:3]
        ]
        probe_attached_anime.append({
            "anime_uuid": str(a.uuid), "title": a.title,
            "name_eng": a.name_eng, "name_jap": a.name_jap, "media": media,
        })
    probe_attached_media_count = sum(len(e["media"]) for e in probe_attached_anime)

    # --- 10 step-1 refresh failures + 3 probe failures (later in the pool) ---
    fail_pool = [a for a in animes if a not in attach_pool]
    step1_failures = []
    for i, a in enumerate(fail_pool[:10]):
        outage = i % 2 == 0
        step1_failures.append({
            "anime_uuid": str(a.uuid),
            "title": a.title,
            "name_eng": a.name_eng,
            "name_jap": a.name_jap,
            "error_category": "upstream_outage" if outage else None,
            "error_message": (
                "MAL returned 503 Service Unavailable after 5 retries"
                if outage else "KeyError: 'episodes' missing from /full payload"
            ),
        })
    probe_failures = [
        {
            "anime_uuid": str(a.uuid),
            "title": a.title,
            "name_eng": a.name_eng,
            "name_jap": a.name_jap,
            "error_category": "upstream_outage",
            "error_message": "Relations probe timed out fetching /relations",
        }
        for a in fail_pool[10:13]
    ]

    # --- umbrella ("Anime changes") drift: 3 entries ---
    umb_pool = [a for a in fail_pool[13:16]]
    anime_umbrella_changes = []
    field_sets = [
        [{"field": "cover_image", "old": "https://cdn.myanimelist.net/images/anime/old.jpg",
          "new": "https://cdn.myanimelist.net/images/anime/new.jpg"}],
        [{"field": "description", "old": "An old synopsis.", "new": "A revised, longer synopsis."}],
        [{"field": "title", "old": "Old Romaji Title", "new": "New Romaji Title"},
         {"field": "name_eng", "old": "Old English", "new": "New English"}],
    ]
    for a, fields in zip(umb_pool, field_sets):
        title_change = any(f["field"] in {"title", "name_eng", "name_jap"} for f in fields)
        anime_umbrella_changes.append({
            "anime_id": a.id,
            "anime_uuid": str(a.uuid),
            "anime_title": a.title,
            "anime_name_eng": a.name_eng,
            "anime_name_jap": a.name_jap,
            "fields": fields,
            "anchor_changed": title_change,
            "old_anchor_mal_id": a.mal_id,
            "new_anchor_mal_id": a.media[0].mal_id if a.media else a.mal_id,
            "embedding_regenerated": title_change,
            "reclassified": (
                [{"mal_id": a.media[0].mal_id, "old": "side_story", "new": "main"}]
                if title_change and a.media else []
            ),
        })

    # --- media changes: a mix of dynamic / static / genre / studio drift ---
    media_changes: list[dict] = []
    change_pool = [a for a in animes if a.media][:12]
    for i, a in enumerate(change_pool):
        m = a.media[0]
        if i % 4 == 0:
            media_changes.append(_media_change(a, m, dynamic=[
                {"field": "score", "old": 7.42, "new": 7.45},
                {"field": "scored_by", "old": 120345, "new": 120781},
            ]))
        elif i % 4 == 1:
            media_changes.append(_media_change(a, m, static=[
                {"field": "description", "old": "Short synopsis.", "new": "Longer, updated synopsis."},
            ]))
        elif i % 4 == 2:
            media_changes.append(_media_change(a, m, genre_drift={
                "field": "genres", "media_mal_id": m.mal_id, "media_title": m.title,
                "kind": "applied_with_unknowns" if include_genre_tags else "applied",
                "old": ["Action"],
                "new": ["Action", "Workplace"] if include_genre_tags else ["Action", "Drama"],
                "unknown_tags": ["Workplace"] if include_genre_tags else [],
            }))
        else:
            media_changes.append(_media_change(a, m, studio_drift={
                "field": "studios", "media_mal_id": m.mal_id, "media_title": m.title,
                "kind": "applied", "old": [], "new": ["Studio Demo"], "unknown_tags": [],
            }))

    media_refreshed = 500
    # Make items_done < items_total so the progress-divergence notice renders:
    # the gap is the media of the 10 step-1-failed anime.
    skipped_by_failure = 28
    counters = {
        "media_refreshed": media_refreshed,
        "anime_touched": 47,
        "media_skipped_fresh": 73,
        "media_with_dynamic_changes": sum(1 for c in media_changes if c["dynamic"]),
        "media_with_static_changes": sum(1 for c in media_changes if c["static"]),
        "umbrella_reclassed": len(anime_umbrella_changes),
        "probe_succeeded": len(probe_attached_anime) + 12,
        "probe_failed": len(probe_failures),
        "probe_attached_anime_count": len(probe_attached_anime),
        "probe_attached_media_count": probe_attached_media_count,
        "orphaned_studios_removed": 4,
        "step1_failed": len(step1_failures),
    }
    return {
        "counters": counters,
        "media_changes": media_changes,
        "anime_umbrella_changes": anime_umbrella_changes,
        "step1_failures": step1_failures,
        "probe_failures": probe_failures,
        "probe_attached_anime": probe_attached_anime,
        "unknown_genre_tags": ["Workplace", "Crime"] if include_genre_tags else [],
        "merge_detect_failed": False,
        "cache_recompute_failed": False,
        "_items_total": media_refreshed + skipped_by_failure,
    }


async def main(apply: bool, do_delete: bool, include_genre_tags: bool) -> None:
    async with async_session_maker() as session:
        # Scope --delete to our own demo rows: the unique marker AND the kind
        # we seed, so a future marker-key collision can't sweep unrelated jobs.
        marker_match = (Job.kind == JobKind.update_sweep) & (
            Job.payload["marker"].astext == _DEMO_MARKER
        )
        if do_delete:
            existing = (await session.execute(
                select(Job).where(marker_match),
            )).scalars().all()
            print(f"Found {len(existing)} demo job(s): {[str(j.uuid)[:8] for j in existing]}")
            if apply and existing:
                await session.execute(delete(Job).where(marker_match))
                await session.commit()
                print("Deleted.")
            elif not apply:
                print("(dry-run — pass --apply to delete)")
            return

        animes = (await session.execute(
            select(Anime).options(selectinload(Anime.media)).order_by(Anime.id).limit(40),
        )).scalars().all()
        if len(animes) < 20:
            print(f"Only {len(animes)} anime in the catalog — seed more first.")
            return

        summary = _build_summary(animes, include_genre_tags=include_genre_tags)
        items_total = summary.pop("_items_total")
        c = summary["counters"]
        print("Demo update_sweep v6 result_summary:")
        print(f"  media_refreshed={c['media_refreshed']} (items {c['media_refreshed']}/{items_total} — divergence notice)")
        print(f"  step1_failures={len(summary['step1_failures'])}  probe_failures={len(summary['probe_failures'])}")
        print(f"  probe_attached_anime={len(summary['probe_attached_anime'])} "
              f"(media_count={c['probe_attached_media_count']}): "
              f"{[e['title'] for e in summary['probe_attached_anime']]}")
        print(f"  anime_umbrella_changes={len(summary['anime_umbrella_changes'])}  "
              f"media_changes={len(summary['media_changes'])}  "
              f"unknown_genre_tags={summary['unknown_genre_tags']}")

        if not apply:
            print("\n(dry-run — pass --apply to insert the job)")
            return

        now = datetime.now(timezone.utc)
        job = make_job(
            JobKind.update_sweep,
            status=JobStatus.succeeded,
            payload={"marker": _DEMO_MARKER, "note": "seeded by scripts.seed_demo_sweep_job"},
            stage="Done",
            items_total=items_total,
            items_done=c["media_refreshed"],
            result_summary=summary,
            requested_by_user_id=None,
            created_at=now - timedelta(seconds=14),
            started_at=now - timedelta(seconds=14),
            finished_at=now,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        print(f"\nInserted demo job uuid={job.uuid} (version={job.version}).")
        print(f"View at /admin/jobs/{job.uuid}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="actually insert/delete (default: dry-run)")
    p.add_argument("--delete", action="store_true", help="remove previously-seeded demo job(s)")
    p.add_argument(
        "--no-genre-tags", action="store_true",
        help="drop unknown genre tags so the row gets NO amber tint — lets the blue "
             "probe-attach tint show in isolation",
    )
    args = p.parse_args()
    asyncio.run(main(apply=args.apply, do_delete=args.delete, include_genre_tags=not args.no_genre_tags))
