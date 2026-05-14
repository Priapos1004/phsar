"""Enable pg_trgm for fuzzy title-search ranking

Revision ID: 4b8f1e3c7d0a
Revises: 9a7e3b8c1d4f
Create Date: 2026-05-14 14:50:00.000000

`apply_vector_ordering` boosts search results whose title contains the
query as a literal substring (case-insensitive ilike). Typos like "lor
of" for "Lord of Mysteries" miss that bonus and end up buried by pure
embedding cosine distance.

pg_trgm provides `similarity(text, text) -> float` based on trigram set
overlap, which handles all typo classes (insertion, deletion,
substitution, transposition). The extension ships with Postgres core —
no install required, just enablement on the DB.

No index added here: the catalog is small enough (~thousands of anime)
that `similarity(...)` per row in an already-filtered candidate set is
sub-50ms. If catalog growth pushes that past a few hundred ms a GIN
trigram index on `anime.title`, `anime.name_eng`, `media.title`,
`media.name_eng` is the follow-up.

"""
from typing import Sequence, Union

from alembic import op

revision: str = "4b8f1e3c7d0a"
down_revision: Union[str, None] = "9a7e3b8c1d4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
