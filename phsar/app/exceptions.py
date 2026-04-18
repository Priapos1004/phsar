from app.core.config import settings


class PhsarBaseError(Exception):
    """Base class for all custom exceptions in the PHSAR project."""
    status_code: int = 400


class MalIdAlreadyExistsError(PhsarBaseError):
    """Raised when a media/anime with the same mal_id already exists in the database."""
    status_code = 409

    def __init__(self, mal_id: int, title: str):
        self.mal_id = mal_id
        self.title = title
        message = f"Media/Anime with mal_id {mal_id} already exists ('{title}')."
        super().__init__(message)


class AnimeNotFoundError(PhsarBaseError):
    """Raised when an anime is not found in the MAL API."""
    status_code = 404

    def __init__(self, title: str):
        self.title = title
        message = f"Anime titled '{title}' not found."
        super().__init__(message)


class MainMediaNotFoundError(PhsarBaseError):
    """Raised when a list of MediaUnconnected has no main media."""
    status_code = 404

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

class UserAlreadyExistsError(PhsarBaseError):
    """Raised when a user tries to register with a username that already exists."""
    status_code = 409

    def __init__(self, username: str):
        self.username = username
        message = f"Username '{username}' already registered."
        super().__init__(message)


class InvalidRegistrationTokenError(PhsarBaseError):
    """Raised when a registration token is not found."""

    def __init__(self):
        message = "Invalid registration token."
        super().__init__(message)


class RegistrationTokenAlreadyUsedError(PhsarBaseError):
    """Raised when a registration token has already been used."""

    def __init__(self):
        message = "This registration token has already been used."
        super().__init__(message)


class RegistrationTokenExpiredError(PhsarBaseError):
    """Raised when a registration token has expired."""

    def __init__(self):
        message = "This registration token has expired."
        super().__init__(message)


class FieldDoesNotExistError(PhsarBaseError):
    """Raised when a requested field does not exist on a model."""

    def __init__(self, field_name: str, model_name: str):
        self.field_name = field_name
        self.model_name = model_name
        message = f"Field '{field_name}' does not exist in model {model_name}"
        super().__init__(message)


class CouldNotValidateCredentialsError(PhsarBaseError):
    """Raised when credentials cannot be validated."""
    status_code = 401

    def __init__(self):
        message = "Could not validate credentials"
        super().__init__(message)

class InsufficientPermissionsError(PhsarBaseError):
    """Raised when a user does not have sufficient permissions to access a resource."""
    status_code = 403

    def __init__(self):
        message = "Insufficient permissions"
        super().__init__(message)

class MissingSearchDataError(PhsarBaseError):
    """Raised when the search data is missing in the token."""

    def __init__(self):
        message = "Missing search data in token"
        super().__init__(message)


class InvalidSearchTypeError(PhsarBaseError):
    """Raised when a search type is not supported for the given endpoint."""

    def __init__(self, search_type: str):
        message = f"Search type '{search_type}' is not supported on this endpoint."
        super().__init__(message)


class RatingNotFoundError(PhsarBaseError):
    """Raised when a rating is not found or not owned by the user."""
    status_code = 404

    def __init__(self, identifier: str):
        message = f"Rating not found: '{identifier}'."
        super().__init__(message)


class MediaNotFoundError(PhsarBaseError):
    """Raised when a media UUID does not resolve to an existing media."""
    status_code = 404

    def __init__(self, media_identifier: str):
        message = f"Media not found: '{media_identifier}'."
        super().__init__(message)


class AnimeNotFoundByUuidError(PhsarBaseError):
    """Raised when an anime UUID does not resolve to an existing anime."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Anime not found: '{uuid}'."
        super().__init__(message)


class UserSettingsNotFoundError(PhsarBaseError):
    """Raised when user settings are not found (should not happen if seeding is correct)."""
    status_code = 404

    def __init__(self):
        message = "User settings not found."
        super().__init__(message)


class RegistrationTokenNotFoundError(PhsarBaseError):
    """Raised when a registration token UUID does not resolve to an existing token."""
    status_code = 404

    def __init__(self, uuid: str):
        message = f"Registration token not found: '{uuid}'."
        super().__init__(message)


class CannotDeleteUsedTokenError(PhsarBaseError):
    """Raised when attempting to delete a registration token that has been used."""
    status_code = 400

    def __init__(self):
        message = "Cannot delete a registration token that has already been used."
        super().__init__(message)


class InvalidPasswordError(PhsarBaseError):
    """Raised when the provided password does not match the user's current password."""
    status_code = 403

    def __init__(self):
        message = "Invalid password."
        super().__init__(message)
