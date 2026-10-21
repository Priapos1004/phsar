"""Store the world each discover spin drew

Revision ID: 58dd3ea5f2e0
Revises: 22fb9edfced7
Create Date: 2026-10-21 20:24:55.244980

Recomputed from the spin count, the day's world moved whenever a release edited the
worlds. Rows spun before this revision get an empty world, which names none, so their
day's world is drawn from the bag as it was until their next spin stores one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58dd3ea5f2e0'
down_revision: Union[str, None] = '22fb9edfced7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('discover_progress', sa.Column('world', sa.String(), nullable=False, server_default=''))
    # Only the backfill needs the default; the model has none, and every spin writes one.
    op.alter_column('discover_progress', 'world', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('discover_progress', 'world')
