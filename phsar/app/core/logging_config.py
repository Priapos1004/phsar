import logging
import sys


def setup_logging():
    logging_config = {
        "level": logging.DEBUG,  # Set to DEBUG during development, INFO/WARNING in prod
        "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "handlers": [
            logging.StreamHandler(sys.stdout)
        ],
    }
    logging.basicConfig(**logging_config)

    # Optionally, tune third-party libraries (uvicorn, sqlalchemy, etc.)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
