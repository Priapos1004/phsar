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
│   │   └── db.py
│   ├── main.py
│   └── models/
│       ├── __init__.py
│       ├── anime.py
│       ├── base.py
│       ├── genre.py
│       ├── media.py
│       ├── media_genre.py
│       ├── media_studio.py
│       ├── ratings.py
│       ├── studio.py
│       ├── tag.py
│       ├── users.py
│       ├── watchlist.py
│       └── watchlist_tag.py
├── frontend/
├── .env
├── README.md
├── alembic/
│   ├── README
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── alembic.ini
└── requirements.txt
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

After setting up the database, run the following commands to create the tables:

```
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head
```

For future changes to the database schemas, run:

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

When first running the FastAPI App, the genre table and the first admin user will be seeded.

```
uvicorn app.main:app --reload
```
