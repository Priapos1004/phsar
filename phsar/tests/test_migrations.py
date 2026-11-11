"""`alembic check` against the suite's own database, which `_database.build` brings up
from the migration chain — so a chain that no longer replays from empty fails the session
before any test runs. What the check catches and misses: `.claude/rules/database.md`."""

from alembic.command import check

from tests._database import alembic_config


def test_the_models_match_the_migrations():
    check(alembic_config())
