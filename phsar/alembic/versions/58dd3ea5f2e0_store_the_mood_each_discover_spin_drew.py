"""Store the mood each discover spin drew

Revision ID: 58dd3ea5f2e0
Revises: 22fb9edfced7
Create Date: 2026-10-21 20:24:55.244980

Recomputed from the spin count, the day's mood moved whenever a release edited the
moods. Rows spun before this revision get an empty mood, which names none, so their
day's mood is drawn from the bag as it was until their next spin stores one.
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
    op.add_column('discover_progress', sa.Column('mood', sa.String(), nullable=False, server_default=''))
    # Only the backfill needs the default; the model has none, and every spin writes one.
    op.alter_column('discover_progress', 'mood', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('discover_progress', 'mood')
