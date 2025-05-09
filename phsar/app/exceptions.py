class PhsarBaseError(Exception):
    """Base class for all custom exceptions in the PHSAR project."""
    pass


class MalIdAlreadyExistsError(PhsarBaseError):
    """Raised when a media/anime with the same mal_id already exists in the database."""

    def __init__(self, mal_id: int, title: str):
        self.mal_id = mal_id
        self.title = title
        message = f"Media/Anime with mal_id {mal_id} already exists ('{title}')."
        super().__init__(message)


class AnimeNotFoundError(PhsarBaseError):
    """Raised when an anime is not found in the MAL API."""

    def __init__(self, title: str):
        self.title = title
        message = f"Anime titled '{title}' not found."
        super().__init__(message)


class MainMediaNotFoundError(PhsarBaseError):
    """Raised when a list of MediaUnconnected has no main media."""

    def __init__(self, title_relation_tuple: list[tuple[str, str]]):
        self.title_relation_tuple = title_relation_tuple
        message = f"Main media not found in the list: {title_relation_tuple}."
        super().__init__(message)


class NonNumericFieldError(PhsarBaseError):
    """Raised when a non-numeric field is passed to a numeric stats function."""

    def __init__(self, field_name: str):
        self.field_name = field_name
        message = f"The field '{field_name}' is not a numeric type."
        super().__init__(message)
