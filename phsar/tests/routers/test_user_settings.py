from app.models.users import RoleType

# --- Settings CRUD ---

async def test_get_settings_returns_defaults_after_registration(client, create_user_with_role):
    token = await create_user_with_role(username="settingsuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/settings", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["profile_picture"] == "rainbow"
    assert data["name_language"] == "english"
    assert data["default_search_view"] == "anime"
    assert data["rating_step"] == "0.5"
    assert data["spoiler_level"] == "off"


async def test_get_settings_admin(client, admin_auth_headers):
    """Admin can fetch settings; values may differ from defaults if changed via manual testing."""
    resp = await client.get("/users/settings", headers=admin_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "name_language" in data
    assert "profile_picture" in data
    assert "rating_step" in data


async def test_update_settings_partial(client, create_user_with_role):
    token = await create_user_with_role(username="partialuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    # Update only rating_step
    resp = await client.put("/users/settings", json={"rating_step": "0.25"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["rating_step"] == "0.25"
    # Other fields stay at defaults
    assert resp.json()["name_language"] == "english"
    assert resp.json()["spoiler_level"] == "off"


async def test_update_settings_multiple_fields(client, create_user_with_role):
    token = await create_user_with_role(username="multiuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put(
        "/users/settings",
        json={
            "name_language": "japanese",
            "default_search_view": "media",
            "spoiler_level": "blur",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name_language"] == "japanese"
    assert data["default_search_view"] == "media"
    assert data["spoiler_level"] == "blur"


async def test_update_settings_persists(client, create_user_with_role):
    token = await create_user_with_role(username="persistuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    await client.put("/users/settings", json={"rating_step": "0.01"}, headers=headers)

    resp = await client.get("/users/settings", headers=headers)
    assert resp.json()["rating_step"] == "0.01"


async def test_restricted_user_can_read_and_update_settings(client, restricted_user_auth_headers):
    # Restricted users can view their settings
    resp = await client.get("/users/settings", headers=restricted_user_auth_headers)
    assert resp.status_code == 200

    # Restricted users can update their settings
    resp = await client.put(
        "/users/settings",
        json={"spoiler_level": "hide"},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["spoiler_level"] == "hide"


async def test_settings_unauthenticated(client):
    resp = await client.get("/users/settings")
    assert resp.status_code == 401


# --- Data Export ---

async def test_export_json(client, create_user_with_role):
    token = await create_user_with_role(username="exportuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/export?format=json", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert "attachment" in resp.headers["content-disposition"]

    data = resp.json()
    assert "ratings" in data
    assert "watchlist" in data
    assert isinstance(data["ratings"], list)
    assert isinstance(data["watchlist"], list)


async def test_export_csv(client, create_user_with_role):
    token = await create_user_with_role(username="csvuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/export?format=csv", headers=headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]


async def test_export_default_format_is_json(client, create_user_with_role):
    token = await create_user_with_role(username="defaultfmt", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"


async def test_export_forbidden_for_restricted_user(client, restricted_user_auth_headers):
    resp = await client.get("/users/export", headers=restricted_user_auth_headers)
    assert resp.status_code == 403
