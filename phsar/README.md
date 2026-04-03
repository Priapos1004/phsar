# phsar Webapp

<details>
<summary>Click to see folder structure</summary>

<!-- To regenerate: git ls-files phsar/ | grep -v 'package-lock' | tree --fromfile -n --charset utf-8 -->
<!-- Then collapse ui/ subdirectories to keep it readable -->

```text
phsar/
├── .env                  # local credentials (not tracked)
├── .env.example
├── app/
│   ├── core/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── dependencies.py
│   │   ├── logging_config.py
│   │   └── security.py
│   ├── daos/
│   │   ├── anime_dao.py
│   │   ├── base_dao.py
│   │   ├── base_mal_id_dao.py
│   │   ├── genre_dao.py
│   │   ├── media_dao.py
│   │   ├── media_unwanted_dao.py
│   │   ├── registration_token_dao.py
│   │   ├── studio_dao.py
│   │   └── user_dao.py
│   ├── exceptions.py
│   ├── main.py
│   ├── models/
│   │   ├── anime.py
│   │   ├── base.py
│   │   ├── genre.py
│   │   ├── media.py
│   │   ├── media_genre.py
│   │   ├── media_search.py
│   │   ├── media_studio.py
│   │   ├── media_unwanted.py
│   │   ├── ratings.py
│   │   ├── registration_token.py
│   │   ├── studio.py
│   │   ├── tag.py
│   │   ├── users.py
│   │   ├── watchlist.py
│   │   └── watchlist_tag.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── filters.py
│   │   ├── save.py
│   │   ├── search.py
│   │   └── seeder.py
│   ├── schemas/
│   │   ├── anime_schema.py
│   │   ├── auth_schema.py
│   │   ├── media_filter_schema.py
│   │   ├── media_schema.py
│   │   └── search_schema.py
│   ├── seeders/
│   │   ├── genre_seeder.py
│   │   ├── media_seeder.py
│   │   └── user_seeder.py
│   └── services/
│       ├── anime_service.py
│       ├── auth_service.py
│       ├── filter_service.py
│       ├── jikan_scraper.py
│       ├── media_linking_service.py
│       ├── media_search_service.py
│       ├── media_service.py
│       ├── save_service.py
│       ├── search_service.py
│       ├── token_service.py
│       ├── unwanted_media_service.py
│       └── vector_embedding_service.py
├── frontend/
│   ├── components.json
│   ├── package.json
│   ├── USER_FLOWS.md
│   ├── src/
│   │   ├── app.css
│   │   ├── app.html
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   ├── config.ts
│   │   │   ├── utils.ts
│   │   │   ├── components/
│   │   │   │   ├── DoubleRangeSlider.svelte
│   │   │   │   ├── InfoDiashow.svelte
│   │   │   │   ├── LoadingScreen.svelte
│   │   │   │   ├── MediaInfo.svelte
│   │   │   │   ├── NavBar.svelte
│   │   │   │   ├── ScrollableCard.svelte
│   │   │   │   ├── SearchBar.svelte
│   │   │   │   ├── SkeletonMediaInfo.svelte
│   │   │   │   ├── TagSelect.svelte
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
│   │   │   │       ├── slider/
│   │   │   │       └── textarea/
│   │   │   ├── stores/
│   │   │   │   └── auth.ts
│   │   │   ├── styles/
│   │   │   │   └── classes.ts
│   │   │   ├── types/
│   │   │   │   └── api.ts
│   │   │   └── utils/
│   │   │       ├── cn.ts
│   │   │       ├── formatString.ts
│   │   │       ├── getSeason.ts
│   │   │       ├── index.ts
│   │   │       ├── navigation.ts
│   │   │       └── search.ts
│   │   ├── routes/
│   │   │   ├── +layout.svelte
│   │   │   ├── +layout.ts
│   │   │   ├── +page.svelte
│   │   │   ├── login/
│   │   │   │   └── +page.svelte
│   │   │   └── search/
│   │   │       └── +page.svelte
│   │   └── tests/
│   │       ├── setup.ts
│   │       ├── auth-store.test.ts
│   │       ├── format-string.test.ts
│   │       ├── login.test.ts
│   │       ├── navbar.test.ts
│   │       └── searchbar.test.ts
│   ├── static/
│   │   ├── phsar_logo_inverted.png
│   │   └── phsar_logo_transparent.png
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
    │   ├── test_auth.py
    │   ├── test_filters_options.py
    │   ├── test_filters_token.py
    │   ├── test_save.py
    │   └── test_search_media.py
    └── services/
        ├── test_jikan_scraper.py
        ├── test_search_service.py
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

When first running the FastAPI App, the genre table and the first admin user will be seeded. For running the app, use:

```
uvicorn app.main:app --reload
```

You can now open `http://127.0.0.1:8000` to see if the API is live.

## Run Frontend

From `frontend/`:

```
npm install
npm run dev -- --open
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
npm run test
```

## Trouble-shooting

- Check that the database docker container is running!

## License

[PolyForm Noncommercial 1.0.0](../LICENSE) — free for personal, educational, and non-commercial use.
