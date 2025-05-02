from app.daos.base_mal_id_dao import MalIdDAO
from app.models.media_unwanted import MediaUnwanted


class MediaUnwantedDAO(MalIdDAO[MediaUnwanted]):
    def __init__(self):
        super().__init__(MediaUnwanted)
