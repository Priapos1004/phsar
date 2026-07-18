import pytest

from app.services.vector_embedding_service import generate_embedding


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
