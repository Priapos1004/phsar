from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.genre import Genre, GenreType

MAL_GENRES = [
    (1, "Action", "genre"), (2, "Adventure", "genre"), (5, "Avant Garde", "theme"), (46, "Award Winning", "theme"),
    (28, "Boys Love", "demographic"), (4, "Comedy", "genre"), (8, "Drama", "genre"), (10, "Fantasy", "genre"),
    (26, "Girls Love", "demographic"), (47, "Gourmet", "theme"), (14, "Horror", "genre"), (7, "Mystery", "genre"),
    (22, "Romance", "genre"), (24, "Sci-Fi", "genre"), (36, "Slice of Life", "theme"), (30, "Sports", "genre"),
    (37, "Supernatural", "genre"), (41, "Suspense", "theme"), (9, "Ecchi", "explicit_genre"), (49, "Erotica", "explicit_genre"),
    (12, "Hentai", "explicit_genre"), (50, "Adult Cast", "theme"), (51, "Anthropomorphic", "theme"), (52, "CGDCT", "theme"),
    (53, "Childcare", "theme"), (54, "Combat Sports", "theme"), (81, "Crossdressing", "theme"), (55, "Delinquents", "theme"),
    (39, "Detective", "theme"), (56, "Educational", "theme"), (57, "Gag Humor", "theme"), (58, "Gore", "theme"),
    (35, "Harem", "theme"), (59, "High Stakes Game", "theme"), (13, "Historical", "genre"), (60, "Idols (Female)", "theme"),
    (61, "Idols (Male)", "theme"), (62, "Isekai", "theme"), (63, "Iyashikei", "theme"), (64, "Love Polygon", "theme"),
    (65, "Magical Sex Shift", "theme"), (66, "Mahou Shoujo", "theme"), (17, "Martial Arts", "genre"), (18, "Mecha", "genre"),
    (67, "Medical", "theme"), (38, "Military", "genre"), (19, "Music", "genre"), (6, "Mythology", "theme"),
    (68, "Organized Crime", "theme"), (69, "Otaku Culture", "theme"), (20, "Parody", "genre"), (70, "Performing Arts", "theme"),
    (71, "Pets", "theme"), (40, "Psychological", "genre"), (3, "Racing", "genre"), (72, "Reincarnation", "theme"),
    (73, "Reverse Harem", "theme"), (74, "Love Status Quo", "theme"), (21, "Samurai", "genre"), (23, "School", "theme"),
    (75, "Showbiz", "theme"), (29, "Space", "genre"), (11, "Strategy Game", "theme"), (31, "Super Power", "theme"),
    (76, "Survival", "theme"), (77, "Team Sports", "theme"), (78, "Time Travel", "theme"), (32, "Vampire", "theme"),
    (79, "Video Game", "theme"), (80, "Visual Arts", "theme"), (48, "Workplace", "theme"), (82, "Urban Fantasy", "theme"),
    (83, "Villainess", "theme"), (43, "Josei", "demographic"), (15, "Kids", "demographic"), (42, "Seinen", "demographic"),
    (25, "Shoujo", "demographic"), (27, "Shounen", "demographic")
]

MAL_TO_GENRETYPE = {
    "genre": GenreType.Genres,
    "explicit_genre": GenreType.ExplicitGenres,
    "theme": GenreType.Themes,
    "demographic": GenreType.Demographics
}

async def seed_genres(db: AsyncSession):
    for mal_id, name, mal_type in MAL_GENRES:
        result = await db.execute(select(Genre).where(Genre.name == name))
        genre = result.scalars().first()
        if not genre:
            new_genre = Genre(
                name=name,
                genre_type=MAL_TO_GENRETYPE[mal_type]
            )
            db.add(new_genre)
    await db.commit()