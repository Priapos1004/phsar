# phsar Webapp

<details>
<summary>Click to see folder structur</summary>
<!--
Command for creating the tree graphic:
tree phsar -a -F -I '__pycache__|*.pyc|*.pyo|*.db|*.sqlite3|*.log|*.tmp'
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
│   │   └── logging_config.py
│   ├── daos/
│   │   ├── __init__.py
│   │   ├── anime_dao.py
│   │   ├── base_dao.py
│   │   ├── base_mal_id_dao.py
│   │   ├── genre_dao.py
│   │   ├── media_dao.py
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
│   │   ├── ratings.py
│   │   ├── studio.py
│   │   ├── tag.py
│   │   ├── users.py
│   │   ├── watchlist.py
│   │   └── watchlist_tag.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── save.py
│   │   └── search.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── anime_schema.py
│   │   ├── media_schema.py
│   │   └── search_schema.py
│   ├── seeders/
│   │   ├── __init__.py
│   │   ├── genre_seeder.py
│   │   └── user_seeder.py
│   └── services/
│       ├── __init__.py
│       ├── anime_service.py
│       ├── jikan_scraper.py
│       ├── media_linking_service.py
│       ├── media_service.py
│       ├── save_service.py
│       ├── search_service.py
│       └── vector_embedding_service.py
├── frontend/
├── .env
├── README.md
├── alembic/
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── alembic.ini
├── pytest.ini
├── requirements.txt
└── tests/
    ├── __init__.py
    ├── routers/
    │   ├── __init__.py
    │   ├── conftest.py
    │   └── test_save.py
    └── services/
        ├── __init__.py
        └── test_search_service.py
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
```

*Change `animeuser`, `animepass`, `admin`, and `supersecretpassword`*

### Use alembic to Savely Migrate Changes

#### Activate vector Extension in Database

After setting up the database, we need to first activate the vector extension in the database. Fot this, run the command:

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

For testing the `search/mal` and `save/search-results` endpoint, use the [test_fastAPI notebook](../notebooks/test_fastAPI.ipynb).

*Note: Big anime franchises like "Naruto" can take more than 15 minutes to run.*

## Testing

Run the following command to use pytest *(all changes to the database during the tests are rolled-back afterwards)*:

```
pytest
```
