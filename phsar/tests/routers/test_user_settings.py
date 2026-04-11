from app.models.users import RoleType
from app.services.admin_service import DELETED_USER_DISPLAY

# --- Settings CRUD ---

async def test_get_settings_returns_defaults_after_registration(client, create_user_with_role):
    token = await create_user_with_role(username="settingsuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/settings", headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["theme"] == "default"
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
    assert "theme" in data
    assert "rating_step" in data


async def test_update_theme(client, create_user_with_role):
    token = await create_user_with_role(username="themeuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put("/users/settings", json={"theme": "blue"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["theme"] == "blue"

    # Verify it persists
    resp = await client.get("/users/settings", headers=headers)
    assert resp.json()["theme"] == "blue"


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
    assert isinstance(data, list)


async def test_export_json_filename_contains_date(client, create_user_with_role):
    token = await create_user_with_role(username="dateuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/users/export?format=json", headers=headers)
    disposition = resp.headers["content-disposition"]
    # Filename should match phsar_export_{username}_{YYYY_MM_DD}.json
    assert "phsar_export_dateuser_" in disposition
    assert disposition.endswith(".json")


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


# --- Account Deletion ---


async def test_delete_account(client, create_user_with_role):
    token = await create_user_with_role(username="deleteuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.request("DELETE", "/users/account", json={"password": "pass123"}, headers=headers)
    assert resp.status_code == 204

    # Token is now invalid — any authenticated request should fail
    resp2 = await client.get("/users/settings", headers=headers)
    assert resp2.status_code == 401


async def test_delete_account_wrong_password(client, create_user_with_role):
    token = await create_user_with_role(username="wrongpwuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.request("DELETE", "/users/account", json={"password": "wrong"}, headers=headers)
    assert resp.status_code == 403

    # Account still exists
    resp2 = await client.get("/users/settings", headers=headers)
    assert resp2.status_code == 200


async def test_delete_account_cascades_ratings(client, create_user_with_role, admin_auth_headers):
    """Deleting an account removes all user ratings via DB cascade."""
    token = await create_user_with_role(username="cascadeuser", password="pass123", role=RoleType.User)
    headers = {"Authorization": f"Bearer {token}"}

    # Verify settings exist before deletion
    resp = await client.get("/users/settings", headers=headers)
    assert resp.status_code == 200

    # Delete account
    resp = await client.request("DELETE", "/users/account", json={"password": "pass123"}, headers=headers)
    assert resp.status_code == 204


async def test_delete_account_preserves_registration_tokens(client, create_user_with_role, admin_auth_headers):
    """After account deletion, registration tokens created by/used by the user still exist."""
    # Create a token via admin, then register a user with it
    create_resp = await client.post(
        "/admin/registration-tokens",
        json={"role": "user"},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "tokenpreserveuser",
        "password": "pass123",
        "registration_token": reg_token,
    })

    # Login and delete account
    login_resp = await client.post(
        "/auth/login",
        data={"username": "tokenpreserveuser", "password": "pass123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    user_token = login_resp.json()["access_token"]

    resp = await client.request(
        "DELETE", "/users/account",
        json={"password": "pass123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 204

    # Admin can still list tokens — the used token still exists with "[deleted]" user
    list_resp = await client.get("/admin/registration-tokens", headers=admin_auth_headers)
    assert list_resp.status_code == 200
    used_token = next((t for t in list_resp.json() if t["token"] == reg_token), None)
    assert used_token is not None
    assert used_token["status"] == "used"
    assert used_token["used_by"] == DELETED_USER_DISPLAY


async def test_used_token_cannot_register_after_account_deletion(client, admin_auth_headers):
    """A registration token that was used remains blocked even after the user deletes their account."""
    # Create token and register a user
    create_resp = await client.post(
        "/admin/registration-tokens",
        json={"role": "user"},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "reuse_test_user",
        "password": "password123",
        "registration_token": reg_token,
    })

    # Login and delete account
    login_resp = await client.post(
        "/auth/login",
        data={"username": "reuse_test_user", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    user_token = login_resp.json()["access_token"]
    del_resp = await client.request(
        "DELETE", "/users/account",
        json={"password": "password123"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert del_resp.status_code == 204

    # Attempt to reuse the same token — must fail
    reuse_resp = await client.post("/auth/register", json={
        "username": "reuse_attacker",
        "password": "password123",
        "registration_token": reg_token,
    })
    assert reuse_resp.status_code == 400
    assert "already been used" in reuse_resp.json()["detail"]


async def test_delete_account_restricted_user_forbidden(client, restricted_user_auth_headers):
    """Restricted users cannot delete their account."""
    resp = await client.request(
        "DELETE", "/users/account",
        json={"password": "restrictedpass"},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


async def test_delete_account_unauthenticated(client):
    resp = await client.request("DELETE", "/users/account", json={"password": "pass123"})
    assert resp.status_code == 401
