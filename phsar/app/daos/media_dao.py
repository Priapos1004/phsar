from app.daos.base_mal_id_dao import MalIdDAO
from app.models.media import Media


class MediaDAO(MalIdDAO[Media]):
    def __init__(self):
        super().__init__(Media)
