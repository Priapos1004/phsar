"""Soften the animation-quality floor to "low"

Revision ID: f5c2a8d13e96
Revises: e7b2d4a9f13c
Create Date: 2026-09-21 10:00:00.000000

"bad" reads harsher than the scale needs. In-place enum rename
(PG 10+); existing rating rows pick up the new value automatically.

  animationquality: bad -> low

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f5c2a8d13e96"
down_revision: Union[str, None] = "e7b2d4a9f13c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE animationquality RENAME VALUE 'bad' TO 'low'")


def downgrade() -> None:
    op.execute("ALTER TYPE animationquality RENAME VALUE 'low' TO 'bad'")
