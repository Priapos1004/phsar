from app.daos.base_dao import BaseDAO
from app.models.genre import Genre


class GenreDAO(BaseDAO[Genre]):
    def __init__(self):
        super().__init__(Genre)
