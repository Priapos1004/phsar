"""retype media.aired_from / aired_to to date

Every stored value is midnight UTC, so reading them at UTC is lossless.

Revision ID: b6d1f0a4e93c
Revises: ab91b51de5dc
Create Date: 2026-08-29 11:14:22.508113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6d1f0a4e93c'
down_revision: Union[str, None] = 'ab91b51de5dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("aired_from", "aired_to"):
        op.alter_column(
            "media",
            column,
            type_=sa.Date(),
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
            postgresql_using=f"({column} AT TIME ZONE 'UTC')::date",
        )


def downgrade() -> None:
    for column in ("aired_from", "aired_to"):
        op.alter_column(
            "media",
            column,
            type_=sa.DateTime(timezone=True),
            existing_type=sa.Date(),
            existing_nullable=True,
            postgresql_using=f"{column}::timestamp AT TIME ZONE 'UTC'",
        )
