import logging

from app.core.config import settings
from app.core.security import create_url_token
from app.exceptions import FieldExceedsMaximumNumberOfItemsError, TokenTooLongError
from app.schemas.auth_schema import TokenPayload
from app.schemas.media_filter_schema import ExtendedMediaSearchFilters

logger = logging.getLogger(__name__)

def generate_search_token(filters: ExtendedMediaSearchFilters) -> TokenPayload:
    # Enforce item count limit on all list fields
    for field_name in ExtendedMediaSearchFilters.model_fields.keys():
        value = getattr(filters, field_name, None)

        if value is None:
            continue

        # Check if the field is a list type
        if type(value) is list:
            value_length = len(value)
            if value_length > settings.MAX_ITEMS:
                raise FieldExceedsMaximumNumberOfItemsError(field_name=field_name, item_count=value_length)

    # Generate token
    token = create_url_token(filters.model_dump(exclude_unset=True))

    # Enforce token length limit
    token_length = len(token)
    logger.debug(f"Generated token length: {token_length}")
    if token_length > settings.MAX_TOKEN_LENGTH:
        raise TokenTooLongError(token_length)

    return TokenPayload(token=token)
