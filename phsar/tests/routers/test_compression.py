"""HTTP response compression.

The JSON list endpoints are long runs of repeated field names and compress
~7x, which on a home connection to the VM is the dominant term in their
latency. These tests pin the behaviours that are easy to break by reordering or
reconfiguring the middleware stack.
"""

import gzip

import pytest

from app.models.anime import Anime
from app.models.media import Media, SeasonType
from app.services import backup_service
from tests._helpers import media_kwargs

GZIP_HEADERS = {"Accept-Encoding": "gzip"}

# Mirrors `GZipMiddleware(minimum_size=...)` in main.py.
_GZIP_MINIMUM_SIZE = 1000

# A season no real catalogue entry carries, so the filtered response is the
# fixture's rows and nothing else — the same bytes against CI's empty database
# as against a populated dev one. Sizing the body from whatever the catalogue
# happens to hold is what lets a gzip assertion go quietly vacuous.
_GZIP_ROW_COUNT = 12
_GZIP_SEASON_YEAR = 1901
_GZIP_SEASON = SeasonType.Winter
_GZIP_SEASON_FILTER = f"{_GZIP_SEASON.value} {_GZIP_SEASON_YEAR}"


@pytest.fixture
async def compressible_catalog(db_session):
    """Enough anime in one otherwise-unused season to put `/search/anime` well
    past `minimum_size`. No embeddings: a query-less search never joins
    `anime_search`, which keeps the fixture off the encoder."""
    animes = [
        Anime(mal_id=-81000 - i, title=f"Compression Fixture Anime {i}")
        for i in range(_GZIP_ROW_COUNT)
    ]
    db_session.add_all(animes)
    await db_session.flush()
    db_session.add_all([
        Media(**media_kwargs(
            anime.id, anime.mal_id,
            title=f"Compression Fixture Media {i}",
            anime_season_name=_GZIP_SEASON,
            anime_season_year=_GZIP_SEASON_YEAR,
        ))
        for i, anime in enumerate(animes)
    ])
    await db_session.flush()


async def _season_search(client, headers, accept_encoding):
    """The fixture's rows alone, fetched under a given `Accept-Encoding`.

    Asserts the precondition its callers rest on: httpx decodes transparently,
    so `resp.content` is the uncompressed body, and no assertion in a caller
    means anything unless that body clears `minimum_size`."""
    resp = await client.get(
        "/search/anime",
        params={"anime_season": _GZIP_SEASON_FILTER},
        headers={**headers, "Accept-Encoding": accept_encoding},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.content) > _GZIP_MINIMUM_SIZE, (
        f"fixture body no longer clears minimum_size: {len(resp.content)} bytes"
    )
    return resp


async def test_json_list_response_is_gzipped(
    client, user_auth_headers, compressible_catalog,
):
    """A list response over `minimum_size` comes back gzipped, and the body
    still decodes to the same JSON."""
    resp = await _season_search(client, user_auth_headers, "gzip")
    # The wire header is the proof, not the body.
    assert resp.headers.get("content-encoding") == "gzip", (
        "large list response was not compressed — is GZipMiddleware still registered?"
    )
    assert isinstance(resp.json(), list)


async def test_gzip_is_skipped_without_accept_encoding(
    client, user_auth_headers, compressible_catalog,
):
    """No `Accept-Encoding: gzip` from the client means no compression — the
    middleware must not compress unconditionally."""
    resp = await _season_search(client, user_auth_headers, "identity")
    assert resp.headers.get("content-encoding") != "gzip"


async def test_backup_download_opts_out_of_compression(
    client, admin_auth_headers, backup_dir,
):
    """`pg_dump -Fc` output is already zlib-compressed, so the download sets
    `Content-Encoding: identity` to keep GZipMiddleware from streaming a
    multi-GB archive through gzip for ~0% gain (and dropping Content-Length
    with it). Starlette skips compression whenever a content-encoding is
    already set, so this header IS the opt-out — if it disappears, the opt-out
    silently stops working."""
    dump = await backup_service.create_backup(source=backup_service.BackupSource.manual)

    resp = await client.get(
        f"/admin/backups/{dump.filename}",
        headers={**admin_auth_headers, **GZIP_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-encoding") == "identity"
    # And the bytes really are an uncompressed pg_dump archive, not gzip.
    assert resp.content[:5] == b"PGDMP", resp.content[:16]
    with pytest.raises(gzip.BadGzipFile):
        gzip.decompress(resp.content)
