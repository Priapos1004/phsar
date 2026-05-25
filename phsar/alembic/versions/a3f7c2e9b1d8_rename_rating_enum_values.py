"""Rename rating enum values for softer labels

Revision ID: a3f7c2e9b1d8
Revises: e1f4a5d2c0b8
Create Date: 2026-05-25 12:00:00.000000

Three labels were overclaiming. Soften them with in-place enum
renames (PG 10+); existing rating rows pick up the new value
automatically.

  endingquality:    exceptional -> very_satisfying
  fanservice:       normal      -> medium
  animationquality: outstanding -> very_good

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a3f7c2e9b1d8"
down_revision: Union[str, None] = "e1f4a5d2c0b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE endingquality   RENAME VALUE 'exceptional' TO 'very_satisfying'")
    op.execute("ALTER TYPE fanservice      RENAME VALUE 'normal'      TO 'medium'")
    op.execute("ALTER TYPE animationquality RENAME VALUE 'outstanding' TO 'very_good'")


def downgrade() -> None:
    op.execute("ALTER TYPE endingquality   RENAME VALUE 'very_satisfying' TO 'exceptional'")
    op.execute("ALTER TYPE fanservice      RENAME VALUE 'medium'          TO 'normal'")
    op.execute("ALTER TYPE animationquality RENAME VALUE 'very_good'      TO 'outstanding'")
