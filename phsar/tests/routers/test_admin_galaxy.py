"""POST /admin/galaxy/rebuild and PATCH /admin/galaxy/groups/{uuid} — the admin's
handles on the map: refit it now, and give a sector or region a hand name."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.daos.galaxy_dao import GalaxyDAO
from app.models.galaxy import GalaxyGroup
from app.models.job import Job, JobKind

REBUILD = "/admin/galaxy/rebuild"


@pytest.fixture
async def sector(db_session) -> GalaxyGroup:
    await GalaxyDAO().replace_fit(
        db_session, blob=b"models", params={}, names={}, stars=[],
        groups=[{"level": "sector", "number": 0, "parent": None, "auto_name": "Isekai · Light Novel",
                 "x": 0.0, "y": 0.0, "trained_members": []}],
    )
    return (await db_session.execute(select(GalaxyGroup))).scalar_one()


async def test_rebuild_enqueues_a_job_for_the_admin(client, db_session, admin_auth_headers):
    resp = await client.post(REBUILD, headers=admin_auth_headers)
    assert resp.status_code == 202, resp.text
    job = (await db_session.execute(select(Job).where(Job.uuid == resp.json()["job_uuid"]))).scalar_one()
    assert job.kind is JobKind.galaxy_rebuild
    # The admin's own job, so it shows in their bell.
    assert job.requested_by_user_id is not None


async def test_only_an_admin_rebuilds_or_renames(client, user_auth_headers, sector):
    assert (await client.post(REBUILD, headers=user_auth_headers)).status_code == 403
    resp = await client.patch(f"/admin/galaxy/groups/{sector.uuid}", json={"name": "Mine"}, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.mark.parametrize(("sent", "stored"), [
    ("  Summoned & Stranded ", "Summoned & Stranded"),
    ("   ", None),  # blank clears it, back to the auto name
    (None, None),
])
async def test_rename_sets_or_clears_the_hand_name(client, db_session, admin_auth_headers, sector, sent, stored):
    resp = await client.patch(f"/admin/galaxy/groups/{sector.uuid}", json={"name": sent}, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"uuid": str(sector.uuid), "name": stored, "auto_name": "Isekai · Light Novel"}
    await db_session.refresh(sector)
    assert sector.name == stored


async def test_rename_rejects_an_unknown_group_and_an_overlong_name(client, admin_auth_headers, sector):
    resp = await client.patch(f"/admin/galaxy/groups/{uuid4()}", json={"name": "X"}, headers=admin_auth_headers)
    assert resp.status_code == 404
    resp = await client.patch(f"/admin/galaxy/groups/{sector.uuid}", json={"name": "x" * 61}, headers=admin_auth_headers)
    assert resp.status_code == 422
