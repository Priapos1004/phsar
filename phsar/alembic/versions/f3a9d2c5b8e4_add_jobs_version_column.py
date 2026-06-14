"""Add per-kind schema version column on jobs

Revision ID: f3a9d2c5b8e4
Revises: d7a2f9c5e8b3
Create Date: 2026-06-14 10:00:00.000000

`result_summary` shape may evolve per JobKind (e.g. update_sweep is
about to start writing per-media field diffs, dropping a couple of
legacy aggregate counters in the process). Without a version stamp,
the admin Jobs Log frontend would have to sniff the dict shape on
every render. Add an integer `version` column to `jobs` so the
producer side declares the schema explicitly; the frontend switches
on `(kind, version)` to pick a parser.

server_default="1" backfills every existing row in the same DDL
statement — no separate data migration needed. The runtime
`JOB_KIND_VERSIONS` registry in `app/core/job_versions.py` is the
source of truth for new inserts; the server_default is defence-in-
depth so a forgotten registry write can't crash inserts.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a9d2c5b8e4"
down_revision: Union[str, None] = "d7a2f9c5e8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "version")
