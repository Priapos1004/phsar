import logging

from anyio import to_thread
from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime_search import AnimeSearch
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch

logger = logging.getLogger(__name__)

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

async def generate_embedding(text: str) -> list[float]:
    return await to_thread.run_sync(lambda: model.encode(text).tolist(), abandon_on_cancel=True)


async def _create_search_embedding(db: AsyncSession, model_class, fk_kwargs: dict, title_texts: list[str], description_text: str):
    """Shared helper for creating title + description embeddings and persisting them."""
    combined_text = " ".join([t for t in title_texts if t])
    title_embedding = await generate_embedding(combined_text)
    description_embedding = await generate_embedding(f"{combined_text} {description_text}")

    obj = model_class(**fk_kwargs, title_embedding=title_embedding, description_embedding=description_embedding)
    db.add(obj)
    await db.flush()


async def create_media_embedding(db: AsyncSession, media_id: int, title_texts: list[str], description_text: str):
    await _create_search_embedding(db, MediaSearch, {"media_id": media_id}, title_texts, description_text)


async def create_anime_embedding(db: AsyncSession, anime_id: int, title_texts: list[str], description_text: str):
    await _create_search_embedding(db, AnimeSearch, {"anime_id": anime_id}, title_texts, description_text)


async def create_rating_embedding(db: AsyncSession, rating_id: int, note: str):
    embedding = await generate_embedding(note)
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))
    await db.flush()
