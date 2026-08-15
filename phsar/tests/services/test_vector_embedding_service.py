import pytest

from app.services.vector_embedding_service import (
    _encode_query_cached,
    generate_embedding,
    generate_query_embedding,
)


@pytest.mark.asyncio
async def test_generate_embedding():
    text = "Fake Anime Title, Fake Anime English, フェイクアニメ, Fake Alt Title"
    embedding = await generate_embedding(text)

    # Ensure it's a list
    assert isinstance(embedding, list), "Embedding is not a list"

    # Ensure it's not nested
    assert not any(isinstance(x, list) for x in embedding), "Embedding is nested (list of lists)"

    # Ensure all elements are floats
    assert all(isinstance(x, float) for x in embedding), "Embedding contains non-float elements"

    # Check embedding size
    assert len(embedding) == 384, "Unexpected embedding size"


@pytest.mark.asyncio
async def test_generate_embedding_is_case_insensitive():
    """The model is *cased*, so before the case-fold the same query in
    different capitalisation produced different vectors — enough to reorder
    title search and bury the intended show (capitalising "kurokos" dropped
    Kuroko's Basketball off the page). `generate_embedding` lowercases so
    the query and the stored documents share one case space."""
    lower = await generate_embedding("kurokos")
    upper = await generate_embedding("KUROKOS")
    title = await generate_embedding("Kurokos")
    assert lower == upper == title


@pytest.mark.asyncio
async def test_repeated_query_is_served_from_the_cache():
    """The encode is ~30 ms and sits on the request path of every text search, so
    the QUERY path is memoized on the case-folded text — differently-capitalised
    spellings of one query share a single entry instead of each paying for their
    own encode."""
    text = "a query used only by the cache-hit test"
    before = _encode_query_cached.cache_info()

    first = await generate_query_embedding(text)
    after_miss = _encode_query_cached.cache_info()
    assert after_miss.misses == before.misses + 1
    assert after_miss.hits == before.hits

    # Same folded key via a different capitalisation — must hit, not re-encode.
    second = await generate_query_embedding(text.upper())
    after_hit = _encode_query_cached.cache_info()
    assert after_hit.hits == before.hits + 1
    assert after_hit.misses == after_miss.misses

    assert first == second


@pytest.mark.asyncio
async def test_cache_hits_do_not_alias_the_returned_list():
    """The cached value is shared by every caller of a key, and callers assign
    the result to ORM attributes — so a hit must hand back a fresh list. If it
    returned the cached object, one caller mutating its embedding would corrupt
    every later hit on that text."""
    text = "a query used only by the aliasing test"
    first = await generate_query_embedding(text)
    second = await generate_query_embedding(text)

    assert first == second
    assert first is not second, "cache handed the same mutable list to two callers"

    first[0] = 999.0
    third = await generate_query_embedding(text)
    assert third[0] != 999.0, "mutating a returned list leaked into the cache"


@pytest.mark.asyncio
async def test_query_and_document_paths_produce_the_same_vector():
    """Queries are memoized and documents are not, but they MUST still land in one
    case space — that shared fold is the whole precondition for retrieval working.
    Splitting the two paths is exactly the change that could drift them apart, so
    pin that the same text embeds identically either way, in either casing."""
    text = "Kurokos Basketball"
    assert await generate_query_embedding(text) == await generate_embedding(text)
    assert await generate_query_embedding(text.upper()) == await generate_embedding(text.lower())
