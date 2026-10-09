"""Drop the title embeddings from anime_search and media_search

Revision ID: f0449ba5a7d4
Revises: c7e2a9f4b1d8
Create Date: 2026-10-09 12:00:00.000000

Drops every row's title vector (9.2 MB over the dev catalogue's 6,119 rows): title
search matches literally and nothing reads them, while each save still paid an
encode for them. Why drop rather than keep them for later, and what re-adding
costs: compound-docs/2026-10-07-v0.16.0-search-rework.md.

Downgrade re-adds the columns nullable and empty — a migration cannot encode, and
NOT NULL cannot hold over existing rows. The older code writes them for new rows,
and its EMBEDDING_REEMBED_ON_STARTUP pass refills the rest.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = "f0449ba5a7d4"
down_revision: Union[str, None] = "c7e2a9f4b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ("anime_search", "media_search")


def upgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "title_embedding")


def downgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("title_embedding", Vector(384), nullable=True))
