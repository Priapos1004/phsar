# phsar Webapp

<details>
<summary>Click to see folder structure</summary>
<!--
Command for creating the tree graphic:
tree phsar -a -F -I '__pycache__|node_modules|.git|.svelte-kit|.DS_Store|.pytest_cache|.ruff_cache|*.pyc|*.pyo|*.db|*.sqlite3|*.log|*.tmp'
-->

```text
phsar/
├── app/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── dependencies.py
│   │   ├── logging_config.py
│   │   └── security.py
│   ├── daos/
│   │   ├── __init__.py
│   │   ├── anime_dao.py
│   │   ├── base_dao.py
│   │   ├── base_mal_id_dao.py
│   │   ├── genre_dao.py
│   │   ├── media_dao.py
│   │   ├── media_unwanted_dao.py
│   │   └── studio_dao.py
│   ├── exceptions.py
│   ├── main.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── anime.py
│   │   ├── base.py
│   │   ├── genre.py
│   │   ├── media.py
│   │   ├── media_genre.py
│   │   ├── media_search.py
│   │   ├── media_studio.py
│   │   ├── media_unwanted.py
│   │   ├── ratings.py
│   │   ├── registration_token.py
│   │   ├── studio.py
│   │   ├── tag.py
│   │   ├── users.py
│   │   ├── watchlist.py
│   │   └── watchlist_tag.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── filters.py
│   │   ├── save.py
│   │   ├── search.py
│   │   └── seeder.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── anime_schema.py
│   │   ├── auth_schema.py
│   │   ├── media_filter_schema.py
│   │   ├── media_schema.py
│   │   └── search_schema.py
│   ├── seeders/
│   │   ├── __init__.py
│   │   ├── genre_seeder.py
│   │   ├── media_seeder.py
│   │   └── user_seeder.py
│   └── services/
│       ├── __init__.py
│       ├── anime_service.py
│       ├── auth_service.py
│       ├── filter_service.py
│       ├── jikan_scraper.py
│       ├── media_linking_service.py
│       ├── media_search_service.py
│       ├── media_service.py
│       ├── save_service.py
│       ├── search_service.py
│       ├── unwanted_media_service.py
│       └── vector_embedding_service.py
├── frontend/
│   └── phsar-frontend/
│       ├── .gitignore
│       ├── .npmrc
│       ├── README.md
│       ├── package-lock.json
│       ├── package.json
│       ├── src/
│       │   ├── app.css
│       │   ├── app.d.ts
│       │   ├── app.html
│       │   ├── lib/
│       │   │   ├── components/
│       │   │   │   ├── LoadingScreen.svelte
│       │   │   │   ├── NavBar.svelte
│       │   │   │   └── SearchBar.svelte
│       │   │   ├── config.ts
│       │   │   ├── stores/
│       │   │   │   └── auth.ts
│       │   │   └── utils/
│       │   │       └── getSeason.ts
│       │   └── routes/
│       │       ├── +layout.svelte
│       │       ├── +layout.ts
│       │       ├── +page.svelte
│       │       └── login/
│       │           └── +page.svelte
│       ├── static/
│       │   ├── icons/
│       │   │   ├── logout_icon.png
│       │   │   ├── logout_icon_hover.png
│       │   │   ├── logout_icon_hover_transparent.png
│       │   │   ├── logout_icon_transparent.png
│       │   │   ├── search_icon.png
│       │   │   ├── search_icon_hover.png
│       │   │   ├── search_icon_hover_transparent.png
│       │   │   ├── search_icon_transparent.png
│       │   │   ├── user_icon.png
│       │   │   ├── user_icon_hover.png
│       │   │   ├── user_icon_hover_transparent.png
│       │   │   └── user_icon_transparent.png
│       │   ├── phsar_logo.png
│       │   ├── phsar_logo_inverted.png
│       │   └── phsar_logo_transparent.png
│       ├── svelte.config.js
│       ├── tsconfig.json
│       └── vite.config.ts
├── .env
├── README.md
├── alembic/
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── alembic.ini
├── pyproject.toml
├── pytest.ini
├── requirements.txt
└── tests/
    ├── __init__.py
    ├── routers/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── test_auth.py
    │   ├── test_filters.py
    │   ├── test_save.py
    │   └── test_search_media.py
    └── services/
        ├── __init__.py
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
```

*Change `animeuser`, `animepass`, `admin`, `supersecretpassword`, and `supersecretsecretkey`*

### Use alembic to Savely Migrate Changes

#### Activate vector Extension in Database

After setting up the database, we need to first activate the vector extension in the database. For this, run the command:

```
alembic revision -m "create pgvector extension"
```

The go to `alembic/versions/<hash value>_create_pgvector_extension.py` and change the `upgrade()` and `downgrade()` functions to:

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

You can now open

```
http://127.0.0.1:8000
```

to see if the API is live.

For testing the `auth/`, `filters/`, `search/mal`, `search/media`, `seed/media`, and `save/search-results` endpoints, use the [test_fastAPI notebook](../notebooks/test_fastAPI.ipynb).

*Note: Big anime franchises like "Naruto" can take more than 15 minutes to run.*

## Testing

Run the following command to use pytest *(all changes to the database during the tests are rolled-back afterwards)*:

```
pytest
```

## Run Frontend

See [Svelte README](frontend/phsar-frontend/README.md) or just run in `frontend/phsar-frontend`:

```
npm run dev -- --open
```

*FastAPI and Svelte need to run at the same time in two terminals!*

## Trouble-shooting

- Check that the database docker container is running!
