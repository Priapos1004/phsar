"""Which database the suite runs against.

Python runs this before any module under `tests` — conftest included — so it runs before
anything imports `app.core.db`, which builds its engine from `settings` once. Every
connection the suite makes reads the name from there, `pg_dump` included.
"""

import os

from app.core.config import settings

ON_DEV_DB = os.environ.get("PHSAR_TEST_DB") == "dev"
WORKER = os.environ.get("PYTEST_XDIST_WORKER")

if WORKER:
    # Workers share the cores: one thread each, set before torch or numpy load, keeps them
    # from oversubscribing the machine.
    os.environ.setdefault("OMP_NUM_THREADS", "1")

if not ON_DEV_DB:
    # A database per pytest-xdist worker. The worker id goes before `_test`, because
    # `_database.build` drops no database whose name ends otherwise.
    suffix = f"_{WORKER}" if WORKER else ""
    settings.DB_NAME = f"{settings.DB_NAME}{suffix}_test"
