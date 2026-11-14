"""Start the recommender's history at a rating instead of a day

Revision ID: 8d3f6a2c1e74
Revises: 4b7e1c9d2a60
Create Date: 2026-11-14 18:00:00.000000

Replaces `user_settings.history_start` (a date) with `history_start_rating_id`, the rating the
user's own watching order starts at. A day cannot separate the import's last rating from a
natural one made later that day. Deleting the rating returns the user to the detected start.

No date is carried over: the column shipped in the previous revision, unreleased.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8d3f6a2c1e74'
down_revision: Union[str, None] = '4b7e1c9d2a60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user_settings', 'history_start')
    op.add_column('user_settings', sa.Column(
        'history_start_rating_id', sa.Integer(), sa.ForeignKey('ratings.id', ondelete='SET NULL'), nullable=True,
    ))


def downgrade() -> None:
    op.drop_column('user_settings', 'history_start_rating_id')
    op.add_column('user_settings', sa.Column('history_start', sa.Date(), nullable=True))
