from app.daos.base_dao import BaseDAO
from app.models.studio import Studio


class StudioDAO(BaseDAO[Studio]):
    def __init__(self):
        super().__init__(Studio)
