from app.core.config import settings


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

class FieldExceedsMaximumNumberOfItemsError(PhsarBaseError):
    """Raised when a field in the search filter exceeds the maximum number of items allowed."""

    def __init__(self, field_name: str, item_count: int):
        self.item_count = item_count
        self.field_name = field_name
        message = f"'{field_name}' exceeds maximum allowed items ({item_count} > {settings.MAX_ITEMS}) to keep token size manageable."
        super().__init__(message)

class TokenTooLongError(PhsarBaseError):
    """Raised when the generated search token exceeds the maximum length."""

    def __init__(self, token_length: int):
        self.token_length = token_length
        message = f"Generated token is too long (size {token_length} > {settings.MAX_TOKEN_LENGTH}). Please reduce the number of filters."
        super().__init__(message)

class DecompressionError(PhsarBaseError):
    """Raised when decompression of a search token fails."""

    def __init__(self):
        message = "Failed to decompress search token"
        super().__init__(message)

class TokenVersionMismatchError(PhsarBaseError):
    """Raised when the token version does not match the current search API version."""

    def __init__(self, token_version: str):
        self.token_version = token_version
        message = f"Token version '{token_version}' does not match current search API version '{settings.CURRENT_SEARCH_API_VERSION}'."
        super().__init__(message)

class MalformedTokenError(PhsarBaseError):
    """Raised when the search token is malformed."""

    def __init__(self):
        message = "Invalid or malformed search token"
        super().__init__(message)

class CouldNotValidateCredentialsError(PhsarBaseError):
    """Raised when credentials cannot be validated."""

    def __init__(self):
        message = "Could not validate credentials"
        super().__init__(message)

class InsufficientPermissionsError(PhsarBaseError):
    """Raised when a user does not have sufficient permissions to access a resource."""

    def __init__(self):
        message = "Insufficient permissions"
        super().__init__(message)

class MissingSearchDataError(PhsarBaseError):
    """Raised when the search data is missing in the token."""

    def __init__(self):
        message = "Missing search data in token"
        super().__init__(message)
