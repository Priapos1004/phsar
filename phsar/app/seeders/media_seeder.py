import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.services.save_service import save_search_results
from app.services.search_service import handle_search_mal_api_results

logger = logging.getLogger(__name__)

POPULAR_ANIME_QUERIES = [
    "One Piece",
    "Attack on Titan",
    "My Hero Academia",
    "Demon Slayer",
    "Jujutsu Kaisen",
    "Naruto",
    "Bleach",
    "Dragon Ball",
    "One Punch Man",
    "Chainsaw Man",
    "Overlord",
    "Sword Art Online",
    "Tokyo Revengers",
    "Death Note",
    "Fullmetal Alchemist",
    "Hunter x Hunter",
    "Fairy Tail",
    "Fate",
    "Black Clover",
    "Mob Psycho 100",
    "Haikyuu!!",
    "Your Name",
    "Dr. Stone",
    "That Time I Got Reincarnated as a Slime",
    "Re:Zero - Starting Life in Another World",
    "The Seven Deadly Sins",
    "Fire Force",
    "Arifureta: From Commonplace to World's Strongest",
    "The Rising of the Shield Hero",
    "Moonlight Fantasy",
    "The irregular at magic high school",
    "My Dress-Up Darling",
    "Kaguya-sama: Love Is War",
    "The Promised Neverland",
    "Steins;Gate",
    "Darling in the Franxx",
    "Classroom of the Elite",
    "Solo Leveling",
    "Vinland Saga",
    "Assassination Classroom",
    "Golden Time",
    "The ancient magus' bride",
    "Parasyte: The Maxim",
    "Wistoria: Wand and Sword",
    "Horimiya",
    "Moshuko Tensei: Jobless Reincarnation",
    "Tower of God",
    "The Apothecary Diaries",
    "Frieren: Beyond Journey's End",
    "Is it wrong to try to pick up girls in a dungeon?",
    "Hells Paradise",
    "Neon Genesis Evangelion",
    "Blue Lock",
    "Blue Exorcist",
    "The saga of Tanya the Evil",
    "Skip and Loafer",
    "Mashle: Magic and Muscles",
    "KonoSuba: God's Blessing on This Wonderful World!",
    "Lycoris Recoil",
    "Shikimori's Not Just a Cutie",
    "The Devil is a Part-Timer!",
    "Ya Boy Kongming!",
    "Goblin Slayer",
    "Log Horizon",
    "Spy x Family",
    "The daily life of the immortal king",
    "Shangri-La Frontier",
    "No Game No Life",
    "Bungo Stray Dogs",
    "JoJo's Bizarre Adventure",
    "Bocchi the Rock!",
    "Wind Breaker",
    "Dan Da Dan",
    "Food Wars! Shokugeki no Soma",
    "Rent-A-Girlfriend",
    "The Quintessential Quintuplets",
    "Gintama",
]

media_dao = MediaDAO()

async def seed_popular_anime(db: AsyncSession, popular_anime_queries: list[str] = POPULAR_ANIME_QUERIES):
    for query in popular_anime_queries:
        logger.info(f"Seeding: {query}")
        results = await handle_search_mal_api_results(db=db, query=query)
        await save_search_results(db, results)
