"""Rating attribute scale changes (v0.14.13)

Revision ID: a7c3e9f1b2d4
Revises: d4f9b2e7a1c6
Create Date: 2026-06-24 14:00:00.000000

- ending_type:    + not_applicable  (auto-set sentinel for unfinished watches,
                   set alongside ending_quality on on_hold/dropped)
- ending_quality: + neutral          (middle anchor for an "it was okay" ending)
- 3d animation:   rename partial->medium, full->heavy, + rare  (frequency scale
                   mirroring fan_service: none/rare/medium/heavy)

ALTER TYPE ... ADD VALUE / RENAME VALUE run in-transaction on PG 12+ (see the
jobkind backup/restore + relationtype AlternativeVersion precedents). Appended
values can't be dropped by PG, so the downgrade only reverses the 3d renames and
documents the additions as one-way.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7c3e9f1b2d4"
down_revision: Union[str, None] = "d4f9b2e7a1c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ending_type / ending_quality: append new values.
    op.execute("ALTER TYPE endingtype ADD VALUE IF NOT EXISTS 'not_applicable'")
    op.execute("ALTER TYPE endingquality ADD VALUE IF NOT EXISTS 'neutral'")
    # 3d animation: rename existing rows in place (partial->medium, full->heavy),
    # then add the new low-frequency bucket.
    op.execute("ALTER TYPE threedanimation RENAME VALUE 'partial' TO 'medium'")
    op.execute("ALTER TYPE threedanimation RENAME VALUE 'full' TO 'heavy'")
    op.execute("ALTER TYPE threedanimation ADD VALUE IF NOT EXISTS 'rare'")


def downgrade() -> None:
    # PG can't DROP enum values, so the appended values (not_applicable on
    # endingtype, neutral on endingquality, rare on threedanimation) are one-way;
    # only the 3d renames are reversible. Rows holding 'rare' would block this
    # downgrade — acceptable for a dev-only rollback.
    op.execute("ALTER TYPE threedanimation RENAME VALUE 'medium' TO 'partial'")
    op.execute("ALTER TYPE threedanimation RENAME VALUE 'heavy' TO 'full'")
