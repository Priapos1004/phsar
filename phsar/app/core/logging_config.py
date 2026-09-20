import logging
import sys


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,  # Set to DEBUG during development, INFO/WARNING in prod
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )

    # Optionally, tune third-party libraries (uvicorn, sqlalchemy, etc.)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
