"""`ix_jobs_scrape_query` must stay usable by the query it exists for.

The index expression is declared in `models/job.py` as raw SQL in Postgres's own
normalized spelling (so `alembic check` stops proposing a drop-and-recreate every
run), while `JobDAO.find_recent_scrape_for_query` builds the same expression with
`func.lower(func.trim(...))`. Two spellings of one expression, in two files.

That drift fails SILENTLY in the direction that matters: edit either side and the
index simply stops being used, the per-POST dedup check degrades to a scan of a
table the seasonal sweep fills with hundreds of rows a week, and `alembic check`
still passes because the model and the database agree with each other.

So this asks POSTGRES whether the two match, rather than comparing SQL strings —
string comparison would need the same normalization that is the thing under test.
"""

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.daos.job_dao import JobDAO
from app.models.job import Job, JobKind


async def test_scrape_dedup_predicate_can_use_its_index(db_session):
    """With sequential scans disabled, the planner must reach for
    `ix_jobs_scrape_query` — which it can only do if the index expression and the
    DAO's predicate are the same expression to Postgres."""
    # Compile the DAO's expression rather than restating it, so a change there is
    # what this test sees. The `kind` filter is required, not incidental: the index
    # is PARTIAL on `kind = 'user_scrape'`, so Postgres can only use it for a query
    # that also constrains kind — as the real dedup lookup does.
    compiled = str(
        select(Job.id)
        .where(Job.kind == JobKind.user_scrape)
        .where(JobDAO.scrape_query_expr() == "some-query")
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        row[0] for row in (await db_session.execute(text(f"EXPLAIN {compiled}"))).all()
    )

    assert "ix_jobs_scrape_query" in plan, (
        "The scrape-dedup predicate no longer matches its index expression, so the "
        "dedup check falls back to a scan. Compare models/job.py's Index against "
        f"JobDAO.scrape_query_expr(). Plan was:\n{plan}"
    )
