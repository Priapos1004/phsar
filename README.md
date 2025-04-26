# phsar
Repository for Code of phsar website + backend

## Setup environment

### Create a new conda environment

```
conda create -yn phsar python=3.12
conda activate phsar
```

### Install necessary libraries in environment

Run the following command in the `phsar/` folder of this repository:

```
pip install -r requirements.txt
```

## Setup local database (recommended way)

First, use [docker](https://www.docker.com/get-started/) to create a database without the need to install [postgresql](https://www.postgresql.org):

```
docker run --name anime-postgres \
  -e POSTGRES_USER=animeuser \
  -e POSTGRES_PASSWORD=animepass \
  -e POSTGRES_DB=anime_db \
  -v pgdata:/var/lib/postgresql/data \
  -p 5432:5432 \
  -d ankane/pgvector
```

*Change `animeuser` and `animepass`*

Second, you can connect to the postgresql database using [pgadmin4](https://www.pgadmin.org):

- host: localhost
- username: animeuser
- password: animepass

Or directly use python with the library [SQLAlchemy](https://www.sqlalchemy.org).

### Remove local setup

Clean up docker *(database + volume)*:

```
docker rm -f anime-postgres
docker volume rm pgdata
```

## Start with the Webapp

Go into the [phsar](phsar/README.md) folder and follow the instructions of the README file.
