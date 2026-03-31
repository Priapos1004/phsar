from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.genre import Genre, GenreType

# Format: (mal_id, name, mal_type, description)
MAL_GENRES = [
    # Genres
    (1, "Action", "genre", "High-energy scenes with fighting, chases, and physical conflict."),
    (2, "Adventure", "genre", "Characters embark on journeys, exploring new places and facing challenges."),
    (4, "Comedy", "genre", "Intended to make the audience laugh through humor and amusing situations."),
    (8, "Drama", "genre", "Emotionally driven stories focusing on realistic characters and conflicts."),
    (10, "Fantasy", "genre", "Set in worlds with magic, mythical creatures, or supernatural elements."),
    (14, "Horror", "genre", "Designed to frighten and unsettle through suspense, shock, or the macabre."),
    (7, "Mystery", "genre", "Revolves around solving puzzles, crimes, or uncovering hidden truths."),
    (22, "Romance", "genre", "Centers on romantic relationships and emotional connections between characters."),
    (24, "Sci-Fi", "genre", "Explores futuristic technology, space exploration, or scientific concepts."),
    (30, "Sports", "genre", "Focuses on athletic competition, training, and teamwork."),
    (37, "Supernatural", "genre", "Features phenomena beyond scientific understanding such as ghosts or psychic powers."),
    (13, "Historical", "genre", "Set in or inspired by a specific historical period or real events."),
    (17, "Martial Arts", "genre", "Centered on hand-to-hand combat and fighting disciplines."),
    (18, "Mecha", "genre", "Features giant robots or mechanical suits, often piloted by humans."),
    (38, "Military", "genre", "Focuses on armed forces, warfare, and military strategy."),
    (19, "Music", "genre", "Revolves around musical performance, bands, or the music industry."),
    (20, "Parody", "genre", "Satirizes or humorously imitates other works, genres, or tropes."),
    (40, "Psychological", "genre", "Explores the mental and emotional states of characters in depth."),
    (3, "Racing", "genre", "Centers on competitive racing with vehicles, bikes, or other means."),
    (21, "Samurai", "genre", "Features samurai culture, swordsmanship, and feudal Japanese settings."),
    (29, "Space", "genre", "Set primarily in outer space or involving interstellar travel."),
    # Themes
    (5, "Avant Garde", "theme", "Experimental or unconventional storytelling and visual styles."),
    (46, "Award Winning", "theme", "Recognized with notable anime or film industry awards."),
    (47, "Gourmet", "theme", "Focuses on cooking, food culture, and culinary experiences."),
    (36, "Slice of Life", "theme", "Depicts everyday experiences and mundane aspects of life."),
    (41, "Suspense", "theme", "Builds tension and uncertainty to keep the audience on edge."),
    (50, "Adult Cast", "theme", "Main characters are adults rather than teenagers or children."),
    (51, "Anthropomorphic", "theme", "Features animals or non-human beings with human characteristics."),
    (52, "CGDCT", "theme", "Cute Girls Doing Cute Things \u2014 lighthearted stories centered on adorable female characters."),
    (53, "Childcare", "theme", "Involves raising, caring for, or bonding with children."),
    (54, "Combat Sports", "theme", "Focuses on one-on-one fighting sports like boxing, wrestling, or MMA."),
    (81, "Crossdressing", "theme", "Characters dress as or present themselves as a different gender."),
    (55, "Delinquents", "theme", "Centers on rebellious youth, gangs, and rough school life."),
    (39, "Detective", "theme", "Features investigation and crime-solving by a detective or sleuth."),
    (56, "Educational", "theme", "Designed to teach or inform the audience about real-world topics."),
    (57, "Gag Humor", "theme", "Comedy driven by quick jokes, sight gags, and absurd situations."),
    (58, "Gore", "theme", "Contains graphic depictions of blood, violence, or bodily harm."),
    (35, "Harem", "theme", "One male character is surrounded by multiple female romantic or admiring interests."),
    (59, "High Stakes Game", "theme", "Characters compete in games where the consequences of losing are severe."),
    (60, "Idols (Female)", "theme", "Follows female idol singers or groups in the entertainment industry."),
    (61, "Idols (Male)", "theme", "Follows male idol singers or groups in the entertainment industry."),
    (62, "Isekai", "theme", "Characters are transported to or reborn in another world."),
    (63, "Iyashikei", "theme", "Healing anime designed to have a calming, soothing effect on the viewer."),
    (64, "Love Polygon", "theme", "Multiple characters have overlapping romantic interests in each other."),
    (65, "Magical Sex Shift", "theme", "Characters undergo a magical change of biological sex."),
    (66, "Mahou Shoujo", "theme", "Magical girl stories where characters transform and use magical powers."),
    (67, "Medical", "theme", "Focuses on healthcare, doctors, or medical procedures."),
    (6, "Mythology", "theme", "Draws from myths, legends, or folklore of various cultures."),
    (68, "Organized Crime", "theme", "Involves criminal organizations such as the yakuza or mafia."),
    (69, "Otaku Culture", "theme", "Depicts the world of anime, manga, and gaming fandom."),
    (70, "Performing Arts", "theme", "Centers on theater, dance, or other stage performances."),
    (71, "Pets", "theme", "Features animal companions and the bond between pets and owners."),
    (72, "Reincarnation", "theme", "Characters are reborn into a new life, often retaining past memories."),
    (73, "Reverse Harem", "theme", "One female character is surrounded by multiple male romantic or admiring interests."),
    (74, "Love Status Quo", "theme", "Romantic tension is maintained without significant progression."),
    (23, "School", "theme", "Set primarily in a school environment with student life as a backdrop."),
    (75, "Showbiz", "theme", "Explores the entertainment industry, celebrity life, or media production."),
    (11, "Strategy Game", "theme", "Features intellectual or strategic competitions like chess or card games."),
    (31, "Super Power", "theme", "Characters possess extraordinary abilities beyond normal humans."),
    (76, "Survival", "theme", "Characters struggle to stay alive in dangerous or hostile conditions."),
    (77, "Team Sports", "theme", "Focuses on team-based athletic competition and group dynamics."),
    (78, "Time Travel", "theme", "Characters move between different points in time."),
    (32, "Vampire", "theme", "Features vampires or vampire-related mythology and lore."),
    (79, "Video Game", "theme", "Set within or heavily involves video game worlds and culture."),
    (80, "Visual Arts", "theme", "Centers on drawing, painting, photography, or other visual arts."),
    (48, "Workplace", "theme", "Set in a professional work environment with job-related stories."),
    (82, "Urban Fantasy", "theme", "Magical or supernatural elements set in a modern urban environment."),
    (83, "Villainess", "theme", "Protagonist is cast as or reincarnated as the villainess of a story."),
    # Explicit genres
    (9, "Ecchi", "explicit_genre", "Contains mildly sexual content such as fan service and suggestive humor."),
    (49, "Erotica", "explicit_genre", "Features explicit sexual content as a central element."),
    # Demographics
    (28, "Boys Love", "demographic", "Focuses on romantic relationships between male characters."),
    (26, "Girls Love", "demographic", "Focuses on romantic relationships between female characters."),
    (43, "Josei", "demographic", "Targeted at adult women, often featuring mature themes and relationships."),
    (15, "Kids", "demographic", "Aimed at young children with age-appropriate content and themes."),
    (42, "Seinen", "demographic", "Targeted at adult men, often featuring complex narratives and mature themes."),
    (25, "Shoujo", "demographic", "Targeted at teenage girls, often emphasizing romance and emotions."),
    (27, "Shounen", "demographic", "Targeted at teenage boys, often emphasizing action and friendship."),
]

MAL_TO_GENRETYPE = {
    "genre": GenreType.Genres,
    "explicit_genre": GenreType.ExplicitGenres,
    "theme": GenreType.Themes,
    "demographic": GenreType.Demographics
}

async def seed_genres(db: AsyncSession):
    result = await db.execute(select(Genre))
    existing = {genre.name: genre for genre in result.scalars().all()}

    dirty = False
    for _, name, mal_type, description in MAL_GENRES:
        genre_type = MAL_TO_GENRETYPE.get(mal_type)
        genre = existing.get(name)
        if genre:
            if genre.description != description or genre.genre_type != genre_type:
                genre.description = description
                genre.genre_type = genre_type
                dirty = True
        else:
            db.add(Genre(name=name, genre_type=genre_type, description=description))
            dirty = True

    if dirty:
        await db.commit()
