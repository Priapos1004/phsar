"""Add the recommender's tables and the watchlist's event log

Revision ID: 4b7e1c9d2a60
Revises: 33adbd8dbf72
Create Date: 2026-11-14 12:00:00.000000

Creates the stored ranking (`recommendations`, `recommendation_state`), the log of what the
Home row showed (`recommendation_exposure`) and the watchlist's history
(`watchlist_events`), plus the two recommender settings.

The watchlist's history is written by a row trigger on `watchlist`, so no write path — a
service, a bulk endpoint, a tag reassignment — can skip it; what it records and how it merges
churn: docs/features/recommender.md, "The watchlist's history".

The log is seeded from every entry found: an `added` row at its `created_at` and, when it
was edited since, a `changed` row at its `modified_at`. Seeded rows carry this migration's
`created_at`, which is how the recommender knows the history is whole only from here on —
entries listed and removed before it were never seen.

Leftover tables, types and the function are dropped first (`.claude/rules/database.md`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4b7e1c9d2a60'
down_revision: Union[str, None] = '33adbd8dbf72'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECOMMENDATION_KINDS = ("continue", "watchlist", "fresh", "recent", "favourite", "popular", "explore")
EVENT_KINDS = ("added", "changed", "removed")

SEED = """
        INSERT INTO watchlist_events (uuid, user_id, media_id, kind, priority, tag_id, at)
        SELECT gen_random_uuid(), user_id, media_id, 'added'::watchlist_event_kind, priority, tag_id, created_at FROM watchlist
        UNION ALL
        SELECT gen_random_uuid(), user_id, media_id, 'changed'::watchlist_event_kind, priority, tag_id, modified_at FROM watchlist
        WHERE modified_at > created_at
"""

LOG_FUNCTION = """
CREATE FUNCTION watchlist_events_log() RETURNS trigger AS $$
DECLARE
    uid integer;
    mid integer;
    present boolean;  -- the entry's state after this write
    prio integer;
    tag integer;
    last watchlist_events%ROWTYPE;
    prev watchlist_events%ROWTYPE;
    before_present boolean;  -- its state before `last`
    since timestamptz;
BEGIN
    IF TG_OP = 'DELETE' THEN
        uid := OLD.user_id; mid := OLD.media_id; present := false; prio := OLD.priority; tag := OLD.tag_id;
        -- A cascade from deleting the user or the media takes their events too: log nothing,
        -- or the new row's foreign key fails the deletion.
        IF NOT EXISTS (SELECT 1 FROM users WHERE id = uid) OR NOT EXISTS (SELECT 1 FROM media WHERE id = mid) THEN
            RETURN NULL;
        END IF;
    ELSE
        uid := NEW.user_id; mid := NEW.media_id; present := true; prio := NEW.priority; tag := NEW.tag_id;
        IF TG_OP = 'UPDATE' AND OLD.priority = NEW.priority AND OLD.tag_id IS NOT DISTINCT FROM NEW.tag_id THEN
            RETURN NULL;
        END IF;
    END IF;

    SELECT * INTO last FROM watchlist_events
     WHERE user_id = uid AND media_id = mid AND at > now() - interval '3 days' ORDER BY at DESC, id DESC LIMIT 1;
    IF FOUND THEN
        SELECT * INTO prev FROM watchlist_events
         WHERE user_id = uid AND media_id = mid AND (at, id) < (last.at, last.id) ORDER BY at DESC, id DESC LIMIT 1;
        before_present := FOUND AND prev.kind <> 'removed';
        -- A rating or watch anywhere in the span the merge would rewrite, or just before it,
        -- makes the events real: a watch and the removal it caused belong together.
        since := coalesce(prev.at, last.at) - interval '3 hours';
        IF NOT EXISTS (SELECT 1 FROM ratings WHERE user_id = uid AND media_id = mid AND modified_at >= since)
           AND NOT EXISTS (SELECT 1 FROM watch_events WHERE user_id = uid AND media_id = mid AND watched_at >= since) THEN
            IF before_present = present AND (NOT present OR (prev.priority = prio AND prev.tag_id IS NOT DISTINCT FROM tag)) THEN
                DELETE FROM watchlist_events WHERE id = last.id;
            ELSE
                UPDATE watchlist_events SET
                    kind = (CASE WHEN NOT before_present THEN 'added' WHEN present THEN 'changed' ELSE 'removed' END)::watchlist_event_kind,
                    priority = CASE WHEN present THEN prio ELSE prev.priority END,
                    tag_id = CASE WHEN present THEN tag ELSE prev.tag_id END,
                    at = now(),
                    modified_at = now()
                WHERE id = last.id;
            END IF;
            RETURN NULL;
        END IF;
    END IF;

    INSERT INTO watchlist_events (uuid, user_id, media_id, kind, priority, tag_id, at)
    VALUES (gen_random_uuid(), uid, mid,
            (CASE TG_OP WHEN 'INSERT' THEN 'added' WHEN 'UPDATE' THEN 'changed' ELSE 'removed' END)::watchlist_event_kind,
            prio, tag, now());
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
"""


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS watchlist_events_log ON watchlist")
    op.execute("DROP FUNCTION IF EXISTS watchlist_events_log()")
    for table in ("watchlist_events", "recommendation_exposure", "recommendation_state", "recommendations"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for name, labels in (("recommendation_kind", RECOMMENDATION_KINDS), ("watchlist_event_kind", EVENT_KINDS)):
        op.execute(f"DROP TYPE IF EXISTS {name}")
        op.execute(f"CREATE TYPE {name} AS ENUM ({', '.join(repr(label) for label in labels)})")

    op.create_table('recommendations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('kind', _enum('recommendation_kind'), nullable=False),
    sa.Column('ref_anime_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['anime_id'], ['anime.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ref_anime_id'], ['anime.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'anime_id', name='uq_recommendations_user_anime')
    )
    op.create_table('recommendation_state',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('inputs_key', sa.String(), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('modified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id'),
    sa.UniqueConstraint('uuid')
    )
    op.create_table('recommendation_exposure',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('anime_id', sa.Integer(), nullable=False),
    sa.Column('best_rank', sa.Integer(), nullable=False),
    sa.Column('kind', _enum('recommendation_kind'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('modified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['anime_id'], ['anime.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('uuid')
    )
    op.create_index('ix_recommendation_exposure_user_anime', 'recommendation_exposure', ['user_id', 'anime_id'], unique=False)
    op.create_table('watchlist_events',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('media_id', sa.Integer(), nullable=False),
    sa.Column('kind', _enum('watchlist_event_kind'), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('tag_id', sa.Integer(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uuid', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('modified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['media_id'], ['media.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('uuid')
    )
    op.create_index('ix_watchlist_events_user_media_at', 'watchlist_events', ['user_id', 'media_id', 'at'], unique=False)
    op.add_column('user_settings', sa.Column('history_start', sa.Date(), nullable=True))
    op.add_column('user_settings', sa.Column('recommend_hot', sa.Boolean(), server_default=sa.text('true'), nullable=False))

    op.execute(SEED)
    op.execute(LOG_FUNCTION)
    op.execute("""
        CREATE TRIGGER watchlist_events_log
        AFTER INSERT OR DELETE OR UPDATE OF priority, tag_id ON watchlist
        FOR EACH ROW EXECUTE FUNCTION watchlist_events_log()
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS watchlist_events_log ON watchlist")
    op.execute("DROP FUNCTION IF EXISTS watchlist_events_log()")
    op.drop_column('user_settings', 'recommend_hot')
    op.drop_column('user_settings', 'history_start')
    op.drop_index('ix_watchlist_events_user_media_at', table_name='watchlist_events')
    op.drop_table('watchlist_events')
    op.drop_index('ix_recommendation_exposure_user_anime', table_name='recommendation_exposure')
    op.drop_table('recommendation_exposure')
    op.drop_table('recommendation_state')
    op.drop_table('recommendations')
    op.execute("DROP TYPE IF EXISTS watchlist_event_kind")
    op.execute("DROP TYPE IF EXISTS recommendation_kind")
