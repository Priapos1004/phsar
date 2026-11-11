"""Which database the suite runs against.

Python runs this before any module under `tests` — conftest included — so it runs before
anything imports `app.core.db`, which builds its engine from `settings` once. Every
connection the suite makes reads the name from there, `pg_dump` included.
"""

import os

from app.core.config import settings

ON_DEV_DB = os.environ.get("PHSAR_TEST_DB") == "dev"

if not ON_DEV_DB:
    settings.DB_NAME = f"{settings.DB_NAME}_test"
