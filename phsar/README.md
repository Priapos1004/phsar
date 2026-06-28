# phsar Webapp

<details>
<summary>Click to see folder structure</summary>

<!-- To regenerate: git ls-files phsar/ | grep -v 'package-lock' | tree --fromfile -n --charset utf-8 -->
<!-- Then collapse ui/ subdirectories to keep it readable -->

```text
phsar/
├── .dockerignore
├── .env                  # local credentials (not tracked)
├── .env.example
├── Dockerfile
├── docker/
│   └── entrypoint.sh     # applies alembic migrations before starting uvicorn
├── app/
│   ├── core/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── dependencies.py
│   │   ├── logging_config.py
│   │   ├── maintenance.py
│   │   ├── maintenance_middleware.py
│   │   └── security.py
│   ├── daos/
│   │   ├── anime_completion_dao.py
│   │   ├── anime_dao.py
│   │   ├── base_dao.py
│   │   ├── base_mal_id_dao.py
│   │   ├── genre_dao.py
│   │   ├── job_dao.py
│   │   ├── media_dao.py
│   │   ├── media_unwanted_dao.py
│   │   ├── merge_candidate_dao.py
│   │   ├── rating_dao.py
│   │   ├── registration_token_dao.py
│   │   ├── search_filters.py
│   │   ├── split_candidate_dao.py
│   │   ├── studio_dao.py
│   │   ├── user_dao.py
│   │   ├── user_settings_dao.py
│   │   └── watch_event_dao.py
│   ├── exceptions.py
│   ├── main.py
│   ├── models/
│   │   ├── anime.py
│   │   ├── anime_completion.py
│   │   ├── anime_freshness.py
│   │   ├── anime_search.py
│   │   ├── base.py
│   │   ├── genre.py
│   │   ├── job.py
│   │   ├── media.py
│   │   ├── media_freshness.py
│   │   ├── media_genre.py
│   │   ├── media_relation_edges.py
│   │   ├── media_search.py
│   │   ├── media_studio.py
│   │   ├── media_unwanted.py
│   │   ├── merge_candidate.py
│   │   ├── rating_search.py
│   │   ├── ratings.py
│   │   ├── registration_token.py
│   │   ├── split_candidate.py
│   │   ├── studio.py
│   │   ├── tag.py
│   │   ├── user_settings.py
│   │   ├── user_visible_media.py
│   │   ├── users.py
│   │   ├── watch_event.py
│   │   ├── watchlist.py
│   │   └── watchlist_tag.py
│   ├── routers/
│   │   ├── admin.py
│   │   ├── admin_completion.py
│   │   ├── admin_jobs.py
│   │   ├── admin_merge.py
│   │   ├── admin_split.py
│   │   ├── auth.py
│   │   ├── filters.py
│   │   ├── jobs.py
│   │   ├── library.py
│   │   ├── maintenance.py
│   │   ├── media.py
│   │   ├── ratings.py
│   │   ├── save.py
│   │   ├── search.py
│   │   ├── seeder.py
│   │   └── users.py
│   ├── schemas/
│   │   ├── admin_schema.py
│   │   ├── anime_schema.py
│   │   ├── auth_schema.py
│   │   ├── backup_schema.py
│   │   ├── genre_schema.py
│   │   ├── job_schema.py
│   │   ├── maintenance_schema.py
│   │   ├── media_filter_schema.py
│   │   ├── media_schema.py
│   │   ├── rating_schema.py
│   │   ├── search_schema.py
│   │   └── user_settings_schema.py
│   ├── seeders/
│   │   ├── anime_title_backfiller.py
│   │   ├── embedding_backfiller.py
│   │   ├── genre_seeder.py
│   │   ├── media_seeder.py
│   │   ├── relation_backfiller.py
│   │   ├── split_candidate_backfiller.py
│   │   └── user_seeder.py
│   └── services/
│       ├── _pg_subprocess.py
│       ├── admin_service.py
│       ├── admin_stats_service.py
│       ├── anime_relation_service.py
│       ├── anime_search_service.py
│       ├── anime_service.py
│       ├── anime_summary.py
│       ├── auth_service.py
│       ├── backup_dispatcher.py
│       ├── backup_service.py
│       ├── completion_service.py
│       ├── export_service.py
│       ├── filter_service.py
│       ├── jikan_scraper.py
│       ├── job_worker.py
│       ├── media_linking_service.py
│       ├── media_search_service.py
│       ├── media_service.py
│       ├── merge_candidate_service.py
│       ├── merge_detection_service.py
│       ├── progress_reporter.py
│       ├── rating_service.py
│       ├── relation_classifier.py
│       ├── save_service.py
│       ├── scrape_dispatcher.py
│       ├── seasonal_sweep_dispatcher.py
│       ├── search_service.py
│       ├── spoiler_service.py
│       ├── split_candidate_service.py
│       ├── token_service.py
│       ├── unwanted_media_service.py
│       ├── user_settings_service.py
│       └── vector_embedding_service.py
├── frontend/
│   ├── .dockerignore
│   ├── Dockerfile
│   ├── bun.lock
│   ├── components.json
│   ├── package.json
│   ├── USER_FLOWS.md
│   ├── src/
│   │   ├── app.css
│   │   ├── app.html
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   ├── config.ts
│   │   │   ├── echarts.ts
│   │   │   ├── themes.ts
│   │   │   ├── utils.ts
│   │   │   ├── components/
│   │   │   │   ├── AttributeBadges.svelte
│   │   │   │   ├── AttributeDetailBars.svelte
│   │   │   │   ├── AttributeRadar.svelte
│   │   │   │   ├── BackLink.svelte
│   │   │   │   ├── BackupsCard.svelte
│   │   │   │   ├── admin/
│   │   │   │   │   ├── AdminJobsLogTab.svelte
│   │   │   │   │   ├── AdminOverviewTab.svelte
│   │   │   │   │   ├── AdminTabNav.svelte
│   │   │   │   │   ├── AnimeUmbrellaCard.svelte
│   │   │   │   │   ├── CompletionStatusCard.svelte
│   │   │   │   │   ├── DismissedDecisionsSection.svelte
│   │   │   │   │   ├── JobDetailCounters.svelte
│   │   │   │   │   ├── JobDetailHeader.svelte
│   │   │   │   │   ├── MediaChangeCard.svelte
│   │   │   │   │   ├── RegistrationTokensCard.svelte
│   │   │   │   │   ├── SweepTiersCard.svelte
│   │   │   │   │   └── types.ts
│   │   │   │   ├── AttributeSelect.svelte
│   │   │   │   ├── BulkRateDialog.svelte
│   │   │   │   ├── DangerZone.svelte
│   │   │   │   ├── DeleteWatchHistoryToggle.svelte
│   │   │   │   ├── DoubleRangeSlider.svelte
│   │   │   │   ├── EChart.svelte
│   │   │   │   ├── GenreBadges.svelte
│   │   │   │   ├── InfoDiashow.svelte
│   │   │   │   ├── JobBell.svelte
│   │   │   │   ├── LoadingScreen.svelte
│   │   │   │   ├── MaintenanceBanner.svelte
│   │   │   │   ├── MediaInfo.svelte
│   │   │   │   ├── MergeCandidatesCard.svelte
│   │   │   │   ├── NavBar.svelte
│   │   │   │   ├── Notice.svelte
│   │   │   │   ├── RatingCard.svelte
│   │   │   │   ├── RatingNeighbors.svelte
│   │   │   │   ├── RatingsOverview.svelte
│   │   │   │   ├── RatingsOverviewAttributes.svelte
│   │   │   │   ├── RatingsOverviewNotes.svelte
│   │   │   │   ├── RatingsOverviewStats.svelte
│   │   │   │   ├── RatingsOverviewTimeline.svelte
│   │   │   │   ├── ratings/        # /ratings page (list + statistics)
│   │   │   │   │   ├── RatedAnimeCard.svelte
│   │   │   │   │   ├── RatingsActivityChart.svelte
│   │   │   │   │   ├── RatingsAlignmentChart.svelte
│   │   │   │   │   ├── RatingsAttributeAnalysis.svelte
│   │   │   │   │   ├── RatingsBandGrid.svelte
│   │   │   │   │   ├── RatingsFilterBar.svelte
│   │   │   │   │   ├── RatingsListTab.svelte
│   │   │   │   │   ├── RatingsScoreHistogram.svelte
│   │   │   │   │   ├── RatingsStatsTab.svelte
│   │   │   │   │   ├── RatingsTabNav.svelte
│   │   │   │   │   ├── RatingsTable.svelte
│   │   │   │   │   ├── RatingsTagChart.svelte
│   │   │   │   │   └── types.ts
│   │   │   │   ├── RelatedMediaCarousel.svelte
│   │   │   │   ├── ScorePercentile.svelte
│   │   │   │   ├── ScrollableCard.svelte
│   │   │   │   ├── SegmentedControl.svelte
│   │   │   │   ├── SpoilerGuard.svelte
│   │   │   │   ├── SearchBar.svelte
│   │   │   │   ├── SkeletonMediaInfo.svelte
│   │   │   │   ├── SplitCandidatesCard.svelte
│   │   │   │   ├── StudioLinks.svelte
│   │   │   │   ├── TagSelect.svelte
│   │   │   │   ├── Toast.svelte
│   │   │   │   ├── TokenExpiryDialog.svelte
│   │   │   │   ├── Tooltip.svelte
│   │   │   │   ├── VersionFooter.svelte
│   │   │   │   └── ui/           # shadcn-svelte components
│   │   │   │       ├── badge/
│   │   │   │       ├── button/
│   │   │   │       ├── card/
│   │   │   │       ├── checkbox/
│   │   │   │       ├── command/
│   │   │   │       ├── dialog/
│   │   │   │       ├── dropdown-menu/
│   │   │   │       ├── input/
│   │   │   │       ├── input-group/
│   │   │   │       ├── label/
│   │   │   │       ├── popover/
│   │   │   │       ├── select/
│   │   │   │       ├── separator/
│   │   │   │       ├── slider/
│   │   │   │       ├── textarea/
│   │   │   │       └── tooltip/
│   │   │   ├── stores/
│   │   │   │   ├── _bumpStore.ts
│   │   │   │   ├── adminJobsFilter.ts
│   │   │   │   ├── auth.ts
│   │   │   │   ├── bell-session.ts
│   │   │   │   ├── genres.ts
│   │   │   │   ├── jobs.ts
│   │   │   │   ├── maintenance.ts
│   │   │   │   ├── ratingsFilter.ts
│   │   │   │   ├── spoilerVisibility.ts
│   │   │   │   └── userSettings.ts
│   │   │   ├── styles/
│   │   │   │   └── classes.ts
│   │   │   ├── types/
│   │   │   │   └── api.ts
│   │   │   └── utils/
│   │   │       ├── chartColors.ts
│   │   │       ├── chartTheme.ts
│   │   │       ├── cn.ts
│   │   │       ├── formatString.ts
│   │   │       ├── getSeason.ts
│   │   │       ├── index.ts
│   │   │       ├── jobBadges.ts
│   │   │       ├── mediaChangeSort.ts
│   │   │       ├── navigation.ts
│   │   │       ├── ratingAttributes.ts
│   │   │       ├── ratingNeighbors.ts
│   │   │       ├── ratingStats.ts
│   │   │       ├── search.ts
│   │   │       └── spoilerFrontier.ts
│   │   ├── routes/
│   │   │   ├── +layout.svelte
│   │   │   ├── +layout.ts
│   │   │   ├── +page.svelte
│   │   │   ├── admin/
│   │   │   │   ├── +layout.svelte
│   │   │   │   ├── +page.svelte
│   │   │   │   └── jobs/
│   │   │   │       └── [uuid]/
│   │   │   │           └── +page.svelte
│   │   │   ├── anime/
│   │   │   │   └── +page.svelte
│   │   │   ├── health/
│   │   │   │   └── +server.ts
│   │   │   ├── library/
│   │   │   │   └── add/
│   │   │   │       └── +page.svelte
│   │   │   ├── login/
│   │   │   │   └── +page.svelte
│   │   │   ├── media/
│   │   │   │   └── +page.svelte
│   │   │   ├── ratings/
│   │   │   │   ├── +layout.svelte
│   │   │   │   └── +page.svelte
│   │   │   ├── register/
│   │   │   │   └── +page.svelte
│   │   │   ├── search/
│   │   │   │   └── +page.svelte
│   │   │   └── settings/
│   │   │       └── +page.svelte
│   │   └── tests/
│   │       ├── setup.ts
│   │       ├── SpoilerGuardTest.svelte
│   │       ├── admin-jobs-filter.test.ts
│   │       ├── api-download.test.ts
│   │       ├── auth-store.test.ts
│   │       ├── backups-card.test.ts
│   │       ├── completion-status-card.test.ts
│   │       ├── format-string.test.ts
│   │       ├── genre-badges.test.ts
│   │       ├── job-bell.test.ts
│   │       ├── job-detail-counters.test.ts
│   │       ├── library-add.test.ts
│   │       ├── login.test.ts
│   │       ├── maintenance-banner.test.ts
│   │       ├── media-change-sort.test.ts
│   │       ├── media-detail.test.ts
│   │       ├── merge-candidates-card.test.ts
│   │       ├── navbar.test.ts
│   │       ├── navigation.test.ts
│   │       ├── rating-attributes.test.ts
│   │       ├── rating-modal.test.ts
│   │       ├── rating-neighbors.test.ts
│   │       ├── rating-stats.test.ts
│   │       ├── searchbar.test.ts
│   │       ├── segmented-control.test.ts
│   │       ├── spoiler-frontier.test.ts
│   │       ├── spoiler-guard.test.ts
│   │       └── studio-links.test.ts
│   ├── static/
│   │   ├── apple-touch-icon.png
│   │   ├── favicon-192x192.png
│   │   ├── favicon-32x32.png
│   │   ├── favicon-512x512.png
│   │   ├── favicon.ico
│   │   ├── phsar_logo_transparent.png
│   │   ├── profile_pics/    # theme character pics (rainbow.png, red.png, blue.png, green.png)
│   │   └── robots.txt
│   ├── svelte.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/         # migration scripts (generated by alembic)
├── alembic.ini
├── pyproject.toml
├── pytest.ini
├── requirements.txt
├── scripts/
│   ├── audit_cross_franchise.py
│   ├── audit_relation_backfill.py
│   ├── backfill_seasonal_sweep_parents.py
│   ├── delete_anime_by_title.py
│   ├── find_anime.py
│   ├── inspect_anime_relations.py
│   ├── inspect_jobs.py
│   └── seed_demo_sweep_job.py
└── tests/
    ├── _helpers.py
    ├── conftest.py
    ├── routers/
    │   ├── conftest.py
    │   ├── test_admin.py
    │   ├── test_admin_completion.py
    │   ├── test_admin_nightly.py
    │   ├── test_admin_seasonal.py
    │   ├── test_admin_sweep.py
    │   ├── test_anime_detail.py
    │   ├── test_auth.py
    │   ├── test_filters_genres.py
    │   ├── test_filters_options.py
    │   ├── test_filters_token.py
    │   ├── test_health.py
    │   ├── test_jobs.py
    │   ├── test_maintenance.py
    │   ├── test_media_detail.py
    │   ├── test_rating_scores.py
    │   ├── test_ratings.py
    │   ├── test_save.py
    │   ├── test_search_anime.py
    │   ├── test_search_anime_filters.py
    │   ├── test_search_media.py
    │   ├── test_search_ranking.py
    │   ├── test_search_ratings.py
    │   └── test_user_settings.py
    ├── seeders/
    │   ├── test_embedding_backfiller.py
    │   └── test_relation_backfiller.py
    └── services/
        ├── test_anime_service.py
        ├── test_backup_jobs.py
        ├── test_backup_service.py
        ├── test_backup_subprocess_failures.py
        ├── test_jikan_scraper.py
        ├── test_job_dao.py
        ├── test_job_worker.py
        ├── test_merge_candidate_service.py
        ├── test_merge_detection.py
        ├── test_merge_preservation.py
        ├── test_progress_reporter.py
        ├── test_relation_classifier.py
        ├── test_save_service.py
        ├── test_score_percentile.py
        ├── test_search_service.py
        ├── test_seasonal_sweep.py
        ├── test_spoiler_cache_db.py
        ├── test_spoiler_service.py
        ├── test_split_candidate_service.py
        ├── test_update_sweep.py
        └── test_vector_embedding_service.py
```
</details>

## Get Started

### Add Credentials for Database and Admin User

Add the file `.env` to the `phsar/` folder with the following content:

```text
DB_USER=animeuser
DB_PASSWORD=animepass
DB_HOST=localhost
DB_PORT=5432
DB_NAME=anime_db
ADMIN_USERNAME=admin
ADMIN_PASSWORD=supersecretpassword
SECRET_KEY=supersecretsecretkey
SEARCH_SECRET_KEY=supersecretsearchsecretkey
# Optional: seeded guest account (restricted_user role, read-only)
# GUEST_USERNAME=guest
# GUEST_PASSWORD=guestpassword

# --- Backups ----------------------------------------------------------------
# Where dumps land. Defaults to ./backups (cwd-relative) so native dev works
# without root; the container Dockerfile sets BACKUP_DIR=/backups.
# BACKUP_DIR=./backups
# pg_restore timeout. Raise if the DB grows large enough that restores
# legitimately take > 10 min — a mid-restore kill leaves the DB half-dropped.
# BACKUP_RESTORE_TIMEOUT_SECONDS=600

# --- Content pipeline (jobs + sweeps) ---------------------------------------
# Shared bearer for every cron-authed endpoint. See "Scheduled jobs" below.
# Empty disables every cron endpoint (they fail closed).
# JOBS_CRON_TOKEN=supersecretcrontoken
# Max queued+running scrape jobs per user (bounds queue DEPTH, not parallelism
# — the worker is sequential because of MAL's ~3 req/s rate limit).
# JOBS_PER_USER_LIMIT=4
# Max user_scrape submissions per user in any trailing 24h window. Counts
# every status (succeeded/failed too) so transient MAL failures can't grant
# unlimited retries; 51st submission returns 429.
# JOBS_DAILY_LIMIT=50
# Dedupe window for /jobs/scrape. Failed jobs don't count.
# JOBS_DEDUPE_HOURS=24
# Bounds the nightly update_sweep batch size.
# JOBS_SWEEP_MAX_PER_RUN=200
# Re-runs the relation classifier over the catalog at lifespan startup. First
# cold start lazy-fetches missing MediaRelationEdges sidecars from MAL at
# 1 req/s (~14 min for an 800-media catalog); subsequent restarts skip already-
# populated rows and finish in seconds. Disable for tight maintenance windows
# on fresh deploys.
# RELATION_BACKFILL_ON_STARTUP=True
# One-shot: regenerate EVERY search embedding in place at startup so the catalog
# picks up a generate_embedding change (the query/document case-fold). Default
# off — a ~5-9 min catalog re-encode on the 2-vCPU VM is wasteful on every
# restart. Flip on for a single deploy, watch for the "Re-embed complete" log,
# then flip off. Runs post-yield in the background so it never blocks /health.
# EMBEDDING_REEMBED_ON_STARTUP=False
```

*Change `animeuser`, `animepass`, `admin`, `supersecretpassword`, `supersecretsecretkey`, and `supersecretsearchsecretkey`*

`SECRET_KEY` and `SEARCH_SECRET_KEY` should be random generated and at least 256 bit *(≈43 characters)*, as they are used to encode the access tokens and url search parameter.

### Use alembic to Safely Migrate Changes

#### Activate vector Extension in Database

After setting up the database, we need to first activate the vector extension in the database. For this, run the command:

```
alembic revision -m "create pgvector extension"
```

Then go to `alembic/versions/<hash value>_create_pgvector_extension.py` and change the `upgrade()` and `downgrade()` functions to:

```
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

def downgrade():
    op.execute("DROP EXTENSION IF EXISTS vector;")
```

Then run the command:

```
alembic upgrade head
```

#### Initial Table creation

After adding the extension, run the following commands to create the tables:

```
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

#### Future Changes

For future changes to the database schemas that you want to do, run the following commands after changing the `app/models/` files:

```
alembic revision --autogenerate -m "Describe change"
alembic upgrade head
```

*Replace `"Describe change"` with actual change description*

*See [alembic](https://alembic.sqlalchemy.org/en/latest/).*

#### Clean the database

Remove the versions saved by alembic and then drop and re-create the database:

```
rm alembic/versions/*.py
docker exec -it anime-postgres psql -U animeuser -d anime_db -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

## Run FastAPI App

When first running the FastAPI App, the genre table, admin user, and optional guest user will be seeded. All users get default settings. For running the app, use:

```
uvicorn app.main:app --reload
```

You can now open `http://127.0.0.1:8000` to see if the API is live.

## Run Frontend

From `frontend/`:

```
bun install
bun run dev -- --open
```

*FastAPI and Svelte need to run at the same time in two terminals!*

## Testing

### Backend

```
pytest
```

All changes to the database during the tests are rolled back afterwards.

### Frontend

```
cd frontend
bun run test
```

## Scheduled jobs

The backend exposes four cron-authed endpoints — all share the same `JOBS_CRON_TOKEN` bearer.

**Recommended (one daily task):** point your cron at the combined nightly endpoint. It enqueues a backup immediately (pg_dump is MVCC-snapshot, no maintenance window needed), an `update_sweep` after `delay_minutes`, and on Sunday UTC a `seasonal_sweep` with the same delay so the weekly catalog pickup piggybacks on the maintenance window.

```sh
curl -fsS -X POST -H "Authorization: Bearer $JOBS_CRON_TOKEN" \
  "http://localhost:8000/admin/jobs/schedule-nightly?delay_minutes=20"
```

**Ad-hoc endpoints** (same token, kept for force-running one job outside the nightly window):

- `POST /admin/backups/auto` — backup only
- `POST /admin/jobs/schedule-sweep?delay_minutes=N` — `update_sweep` only
- `POST /admin/jobs/schedule-seasonal?delay_minutes=N` — `seasonal_sweep` only

`delay_minutes` is bound to `[0, 1440]` on every sweep endpoint and drives the frontend's maintenance-banner countdown.

## Trouble-shooting

- Check that the database docker container is running!

## License

[PolyForm Noncommercial 1.0.0](../LICENSE) — free for personal, educational, and non-commercial use.
