"""Pin README.md's database diagram to the models.

A diagram of a schema rots, and a wrong one is worse than none because people trust
it. So the block is not parsed and compared but regenerated from SQLAlchemy's
metadata and compared whole: anything drawn that moves in the models fails here until
the README moves with it. What is drawn is each column's type, name and PK/FK/UK flag,
and each foreign key's edge; anything else a model declares — a default, an index, a
check, a table-level unique — is not.

Regenerating means the block carries nothing by hand — no notes on an attribute, no
chosen order — which is the price of that: anything written by hand is something this
test could not keep true. To rewrite it, from `phsar/`:

    python -m tests.test_readme_schema
"""

import re
from pathlib import Path

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import MappedColumn

import app.models  # noqa: F401 — registers every table on the metadata
from app.core.db import Base
from app.models.base import BaseModel

README = Path(__file__).resolve().parents[1] / "README.md"

_BLOCK = re.compile(r"(?<=<!-- schema:start -->\n```mermaid\n).*?(?=```\n<!-- schema:end -->)", re.DOTALL)

# Every BaseModel table carries these alike, so the diagram's title names them once.
_BOOKKEEPING = sorted(
    k for k, v in vars(BaseModel).items() if isinstance(v, MappedColumn) and not v.column.primary_key
)


def _type(column: Column) -> str:
    # The DDL type, so enums show their type name and vectors their width; Mermaid takes no spaces.
    return column.type.compile(dialect=postgresql.dialect()).lower().replace(" ", "_")


def _keys(column: Column) -> str:
    keys = [k for k, on in (("PK", column.primary_key), ("FK", column.foreign_keys), ("UK", column.unique)) if on]
    return f" {', '.join(keys)}" if keys else ""


def render() -> str:
    """The README block's body, from the metadata."""
    based = {m.local_table.name for m in Base.registry.mappers if issubclass(m.class_, BaseModel)}
    tables = sorted(Base.metadata.tables.values(), key=lambda t: t.name)
    plain = [t.name for t in tables if t.name not in based]

    edges, entities = [], []
    for table in tables:
        for fk in table.foreign_keys:
            column = fk.parent
            parent = "|o" if column.nullable else "||"
            child = "o|" if column.unique else "o{"
            label = f"{column.name} {fk.ondelete}" if fk.ondelete else column.name
            edges.append(f'    {fk.column.table.name} {parent}--{child} {table.name} : "{label}"')

        hidden = _BOOKKEEPING if table.name in based else []
        columns = sorted((c for c in table.columns if c.name not in hidden), key=lambda c: not c.primary_key)
        entities.append(f"    {table.name} {{")
        entities += [f"        {_type(c)} {c.name}{_keys(c)}" for c in columns]
        entities.append("    }")

    title = f"Every table{' but ' + ', '.join(plain) if plain else ''} also carries {', '.join(_BOOKKEEPING)}"
    header = ["---", f"title: {title}", "config:", "  layout: elk", "---"]
    return "\n".join([*header, "erDiagram", *sorted(edges), *entities]) + "\n"


def test_readme_diagram_matches_the_models():
    match = _BLOCK.search(README.read_text(encoding="utf-8"))
    assert match, "README.md has no <!-- schema:start --> mermaid block for this test to read."
    assert match.group() == render(), "README.md's database diagram is out of date — from phsar/: python -m tests.test_readme_schema"


if __name__ == "__main__":
    text = README.read_text(encoding="utf-8")
    README.write_text(_BLOCK.sub(lambda _: render(), text), encoding="utf-8")
