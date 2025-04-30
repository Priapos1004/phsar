class MalIdAlreadyExistsError(Exception):
    """ Error raised when a media/anime with the same mal_id already exists in the database. """
    def __init__(self, mal_id: int, title: str):
        super().__init__(f"Media/Anime with mal_id {mal_id} already exists ('{title}').")
        self.mal_id = mal_id
        self.title = title

class AnimeNotFoundError(Exception):
    """ Error raised when an anime is not found in the MAL API. """
    def __init__(self, title: str):
        super().__init__(f"Anime titled '{title}' not found.")
