from app.daos.base_mal_id_dao import MalIdDAO
from app.models.anime import Anime


class AnimeDAO(MalIdDAO[Anime]):
    def __init__(self):
        super().__init__(Anime)
