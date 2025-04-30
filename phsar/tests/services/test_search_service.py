import logging

import pytest

from app.exceptions import MainMediaNotFoundError
from app.services.search_service import get_first_main_relation

logger = logging.getLogger(__name__)

def test_get_first_main_relation():
    # Test with a dictionary containing two main relations
    media_dict = {
        0: {"relation_type": "side", "title": "Side Anime", "mal_id": 0},
        1: {"relation_type": "main", "title": "Main Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Side Anime 2", "mal_id": 2},
        3: {"relation_type": "main", "title": "Main Anime 2", "mal_id": 3},
    }
    result = get_first_main_relation(media_dict)
    assert result == 1

    # Test with a dictionary without a main relation
    media_dict = {
        1: {"relation_type": "side", "title": "Side Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Another Side Anime", "mal_id": 2},
    }
    with pytest.raises(MainMediaNotFoundError) as exc_info:
        get_first_main_relation(media_dict)

    logger.debug(f"Error message: '{exc_info.value}'")
