import logging

from sentence_transformers import SentenceTransformer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media_search import MediaSearch

logger = logging.getLogger(__name__)

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

def generate_embedding(text: str) -> list[float]:
    return model.encode(text).tolist()

async def create_media_embedding(db: AsyncSession, media_id: int, texts: list[str]):
    logger.debug(f"DB session: {id(db)}")
    combined_text = " ".join([t for t in texts if t])  # safely combine, ignoring None
    embedding = generate_embedding(combined_text)

    media_search = MediaSearch(media_id=media_id, embedding=embedding)
    db.add(media_search)
    await db.flush()
