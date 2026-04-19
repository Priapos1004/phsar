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
│   │   └── security.py
│   ├── daos/
│   │   ├── anime_dao.py
│   │   ├── base_dao.py
│   │   ├── base_mal_id_dao.py
│   │   ├── genre_dao.py
│   │   ├── media_dao.py
│   │   ├── media_unwanted_dao.py
│   │   ├── rating_dao.py
│   │   ├── registration_token_dao.py
│   │   ├── search_filters.py
│   │   ├── studio_dao.py
│   │   ├── user_dao.py
│   │   └── user_settings_dao.py
│   ├── exceptions.py
│   ├── main.py
│   ├── models/
│   │   ├── anime.py
│   │   ├── anime_search.py
│   │   ├── base.py
│   │   ├── genre.py
│   │   ├── media.py
│   │   ├── media_genre.py
│   │   ├── media_search.py
│   │   ├── media_studio.py
│   │   ├── media_unwanted.py
│   │   ├── rating_search.py
│   │   ├── ratings.py
│   │   ├── registration_token.py
│   │   ├── studio.py
│   │   ├── tag.py
│   │   ├── user_settings.py
│   │   ├── user_visible_media.py
│   │   ├── users.py
│   │   ├── watchlist.py
│   │   └── watchlist_tag.py
│   ├── routers/
│   │   ├── admin.py
│   │   ├── auth.py
│   │   ├── filters.py
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
│   │   ├── media_filter_schema.py
│   │   ├── media_schema.py
│   │   ├── rating_schema.py
│   │   ├── search_schema.py
│   │   └── user_settings_schema.py
│   ├── seeders/
│   │   ├── embedding_backfiller.py
│   │   ├── genre_seeder.py
│   │   ├── media_seeder.py
│   │   └── user_seeder.py
│   └── services/
│       ├── admin_service.py
│       ├── anime_search_service.py
│       ├── anime_service.py
│       ├── auth_service.py
│       ├── backup_service.py
│       ├── export_service.py
│       ├── filter_service.py
│       ├── jikan_scraper.py
│       ├── media_linking_service.py
│       ├── media_search_service.py
│       ├── media_service.py
│       ├── rating_service.py
│       ├── save_service.py
│       ├── search_service.py
│       ├── spoiler_service.py
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
│   │   │   │   ├── BackupsCard.svelte
│   │   │   │   ├── BulkRateDialog.svelte
│   │   │   │   ├── DangerZone.svelte
│   │   │   │   ├── DoubleRangeSlider.svelte
│   │   │   │   ├── EChart.svelte
│   │   │   │   ├── InfoDiashow.svelte
│   │   │   │   ├── LoadingScreen.svelte
│   │   │   │   ├── MediaInfo.svelte
│   │   │   │   ├── NavBar.svelte
│   │   │   │   ├── RatingCard.svelte
│   │   │   │   ├── RatingsOverview.svelte
│   │   │   │   ├── RatingsOverviewAttributes.svelte
│   │   │   │   ├── RatingsOverviewNotes.svelte
│   │   │   │   ├── RatingsOverviewStats.svelte
│   │   │   │   ├── RatingsOverviewTimeline.svelte
│   │   │   │   ├── RelatedMediaCarousel.svelte
│   │   │   │   ├── ScrollableCard.svelte
│   │   │   │   ├── SpoilerGuard.svelte
│   │   │   │   ├── SearchBar.svelte
│   │   │   │   ├── SkeletonMediaInfo.svelte
│   │   │   │   ├── TagSelect.svelte
│   │   │   │   ├── TokenExpiryDialog.svelte
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
│   │   │   │       └── textarea/
│   │   │   ├── stores/
│   │   │   │   ├── auth.ts
│   │   │   │   ├── spoilerVisibility.ts
│   │   │   │   └── userSettings.ts
│   │   │   ├── styles/
│   │   │   │   └── classes.ts
│   │   │   ├── types/
│   │   │   │   └── api.ts
│   │   │   └── utils/
│   │   │       ├── chartColors.ts
│   │   │       ├── cn.ts
│   │   │       ├── formatString.ts
│   │   │       ├── getSeason.ts
│   │   │       ├── index.ts
│   │   │       ├── navigation.ts
│   │   │       ├── search.ts
│   │   │       └── spoilerFrontier.ts
│   │   ├── routes/
│   │   │   ├── +layout.svelte
│   │   │   ├── +layout.ts
│   │   │   ├── +page.svelte
│   │   │   ├── admin/
│   │   │   │   └── +page.svelte
│   │   │   ├── anime/
│   │   │   │   └── +page.svelte
│   │   │   ├── login/
│   │   │   │   └── +page.svelte
│   │   │   ├── media/
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
│   │       ├── api-download.test.ts
│   │       ├── auth-store.test.ts
│   │       ├── format-string.test.ts
│   │       ├── login.test.ts
│   │       ├── media-detail.test.ts
│   │       ├── navbar.test.ts
│   │       ├── rating-modal.test.ts
│   │       ├── searchbar.test.ts
│   │       ├── spoiler-frontier.test.ts
│   │       └── spoiler-guard.test.ts
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
└── tests/
    ├── routers/
    │   ├── conftest.py
    │   ├── test_admin.py
    │   ├── test_anime_detail.py
    │   ├── test_auth.py
    │   ├── test_filters_options.py
    │   ├── test_filters_token.py
    │   ├── test_health.py
    │   ├── test_media_detail.py
    │   ├── test_ratings.py
    │   ├── test_save.py
    │   ├── test_search_anime.py
    │   ├── test_search_media.py
    │   ├── test_search_ratings.py
    │   └── test_user_settings.py
    └── services/
        ├── test_backup_service.py
        ├── test_jikan_scraper.py
        ├── test_search_service.py
        ├── test_spoiler_service.py
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
# Optional: shared bearer secret for POST /admin/backups/auto (scheduled dumps)
# BACKUP_CRON_TOKEN=supersecretcrontoken
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

## Trouble-shooting

- Check that the database docker container is running!

## License

[PolyForm Noncommercial 1.0.0](../LICENSE) — free for personal, educational, and non-commercial use.
