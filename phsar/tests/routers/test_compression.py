"""HTTP response compression.

The JSON list endpoints are long runs of repeated field names and compress
~7x, which on a home connection to the VM is the dominant term in their
latency. These tests pin the three behaviours that are easy to break by
reordering or reconfiguring the middleware stack.
"""

import gzip

import pytest

from app.services import backup_service

GZIP_HEADERS = {"Accept-Encoding": "gzip"}


async def test_json_list_response_is_gzipped(client, user_auth_headers):
    """A list endpoint large enough to clear `minimum_size` comes back gzipped,
    and the body still decodes to the same JSON."""
    resp = await client.get(
        "/search/anime", params={"query": "a"}, headers={**user_auth_headers, **GZIP_HEADERS},
    )
    assert resp.status_code == 200, resp.text
    # httpx transparently decodes, so check the wire header + that decoding worked.
    if resp.headers.get("content-encoding") == "gzip":
        assert isinstance(resp.json(), list)
    else:
        # Body was under minimum_size — assert that's actually why, so this
        # can't silently pass when compression has been removed entirely.
        assert len(resp.content) < 1000, (
            "response is large but was not gzipped — is GZipMiddleware still registered?"
        )


async def test_gzip_is_skipped_without_accept_encoding(client, user_auth_headers):
    """No `Accept-Encoding: gzip` from the client means no compression — the
    middleware must not compress unconditionally."""
    resp = await client.get(
        "/search/anime",
        params={"query": "a"},
        headers={**user_auth_headers, "Accept-Encoding": "identity"},
    )
    assert resp.status_code == 200, resp.text
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
