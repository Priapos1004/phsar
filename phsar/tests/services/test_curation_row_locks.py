"""Every curation resolver reads its candidate under a row lock — the argument
is in docs/features/curation.md under "A candidate resolves once".

This asserts on the emitted SQL rather than on a real race, because the race
needs two connections and the fixtures give each test one transaction that
rolls back. So it cannot prove the race is closed; it fails when someone drops
`for_update=True`, which is how the guard would actually get lost.

The statements are captured with an engine listener rather than `caplog` on
`sqlalchemy.engine.Engine`: the engine is built by the fixture before a test
can raise that logger's level, and nothing is emitted afterwards.
"""

from uuid import uuid4

import pytest
from sqlalchemy import event

from app.daos.delete_candidate_dao import DeleteCandidateDAO
from app.daos.merge_candidate_dao import MergeCandidateDAO
from app.daos.split_candidate_dao import SplitCandidateDAO


@pytest.fixture
def emitted_sql(db_engine):
    """Every statement this engine executes, in order. Removed in teardown — a
    listener left behind keeps appending into the next test's list."""
    statements: list[str] = []

    @event.listens_for(db_engine.sync_engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    yield statements
    event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


async def test_curation_lookups_lock_the_row(db_session, emitted_sql):
    for dao in (DeleteCandidateDAO(), MergeCandidateDAO(), SplitCandidateDAO()):
        # No row needs to exist: the lookup emits its SELECT either way, and it
        # is the statement, not the result, that carries the invariant.
        assert await dao.get_for_resolve(db_session, uuid4()) is None
        assert "FOR UPDATE" in emitted_sql[-1], (
            f"{type(dao).__name__}.get_for_resolve must lock the row it hands "
            f"to a resolver; emitted: {emitted_sql[-1]}"
        )
