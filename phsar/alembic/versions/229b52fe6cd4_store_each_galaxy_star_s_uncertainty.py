"""Store each galaxy star's uncertainty

Revision ID: 229b52fe6cd4
Revises: 33adbd8dbf72
Create Date: 2026-11-04 21:38:14.360875

Stars of the map live at this revision were fitted with no uncertainty term, so they get 0,
which leaves their neighbours as they were. That map is replaced by the rebuild the new
feature version enqueues at the next boot (docs/features/galaxy.md, "When the map is
rebuilt").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '229b52fe6cd4'
down_revision: Union[str, None] = '33adbd8dbf72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('galaxy_stars', sa.Column('uncertainty', sa.Float(), nullable=False, server_default='0'))
    # Only the backfill needs the default; the model has none, and every fit writes one.
    op.alter_column('galaxy_stars', 'uncertainty', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('galaxy_stars', 'uncertainty')
