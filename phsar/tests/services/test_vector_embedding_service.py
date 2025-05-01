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
