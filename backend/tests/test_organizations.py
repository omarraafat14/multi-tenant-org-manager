"""
Tests for sections 3–6: RBAC enforcement and organisation isolation.

Isolation strategy
──────────────────
Every test creates its own organisation(s) via the API. Because all data
queries are filtered by org_id, there is no cross-contamination between
tests even though all tests share the same PostgreSQL database.
Unique emails are generated with random_email() so user creation never
clashes between tests.
"""
from httpx import AsyncClient

from tests.utils.utils import (
    api_login,
    api_register,
    auth_headers,
    new_org,
    new_user,
    random_email,
    random_password,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

async def invite(
    client: AsyncClient,
    admin_token: str,
    org_id: str,
    email: str,
    role: str = "member",
) -> None:
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"email": email, "role": role},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201, f"Invite failed: {resp.text}"


async def setup_org_with_member(
    client: AsyncClient,
) -> tuple[str, str, str]:
    """
    Create an org (admin) and invite one member.
    Returns (admin_token, member_token, org_id).
    """
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    member_email = random_email()
    member_password = random_password()
    await api_register(client, email=member_email, password=member_password)
    await invite(client, admin_token, org_id, member_email)
    member_token = await api_login(client, email=member_email, password=member_password)

    return admin_token, member_token, org_id


async def create_item(
    client: AsyncClient, token: str, org_id: str, details: dict
) -> dict:
    resp = await client.post(
        f"/api/v1/organizations/{org_id}/items",
        json={"item_details": details},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Create item failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Organisation creation
# ---------------------------------------------------------------------------

async def test_creating_org_makes_creator_admin(client: AsyncClient) -> None:
    _, _, token = await new_user(client)
    org_id = await new_org(client, token)

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/users",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["role"] == "admin"


async def test_creating_org_emits_audit_log(client: AsyncClient) -> None:
    _, _, token = await new_user(client)
    org_id = await new_org(client, token)

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/audit-logs",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    actions = [entry["action"] for entry in resp.json()["data"]]
    assert "organization_created" in actions


# ---------------------------------------------------------------------------
# RBAC — member restrictions
# ---------------------------------------------------------------------------

async def test_member_cannot_invite_users(client: AsyncClient) -> None:
    _, member_token, org_id = await setup_org_with_member(client)

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"email": random_email(), "role": "member"},
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


async def test_member_cannot_list_members(client: AsyncClient) -> None:
    _, member_token, org_id = await setup_org_with_member(client)

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/users",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


async def test_member_cannot_view_audit_logs(client: AsyncClient) -> None:
    _, member_token, org_id = await setup_org_with_member(client)

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/audit-logs",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


async def test_member_sees_only_own_items(client: AsyncClient) -> None:
    admin_token, member_token, org_id = await setup_org_with_member(client)

    await create_item(client, admin_token, org_id, {"author": "admin"})
    await create_item(client, member_token, org_id, {"author": "member"})

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/items",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["data"][0]["item_details"]["author"] == "member"


# ---------------------------------------------------------------------------
# RBAC — admin capabilities
# ---------------------------------------------------------------------------

async def test_admin_can_invite_user(client: AsyncClient) -> None:
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    email = random_email()
    await api_register(client, email=email, password=random_password())

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"email": email, "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "member"


async def test_admin_sees_all_items(client: AsyncClient) -> None:
    admin_token, member_token, org_id = await setup_org_with_member(client)

    await create_item(client, admin_token, org_id, {"by": "admin"})
    await create_item(client, member_token, org_id, {"by": "member"})

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/items",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


async def test_admin_can_view_audit_logs(client: AsyncClient) -> None:
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    resp = await client.get(
        f"/api/v1/organizations/{org_id}/audit-logs",
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


async def test_invite_nonexistent_user_is_400(client: AsyncClient) -> None:
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"email": "ghost@nobody.example.com", "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


async def test_invite_already_member_is_400(client: AsyncClient) -> None:
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    email = random_email()
    await api_register(client, email=email, password=random_password())
    await invite(client, admin_token, org_id, email)

    resp = await client.post(
        f"/api/v1/organizations/{org_id}/users",
        json={"email": email, "role": "member"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Organisation isolation
# ---------------------------------------------------------------------------

async def test_non_member_cannot_access_org(client: AsyncClient) -> None:
    _, _, admin_token = await new_user(client)
    org_id = await new_org(client, admin_token)

    _, _, stranger_token = await new_user(client)

    for method, path, kwargs in [
        ("get", f"/api/v1/organizations/{org_id}/items", {}),
        ("get", f"/api/v1/organizations/{org_id}/users", {}),
        ("get", f"/api/v1/organizations/{org_id}/audit-logs", {}),
    ]:
        resp = await getattr(client, method)(
            path, headers=auth_headers(stranger_token), **kwargs
        )
        assert resp.status_code == 403, f"{method.upper()} {path} should be 403"


async def test_member_of_org_a_cannot_access_org_b(client: AsyncClient) -> None:
    admin_a_token, member_token, _ = await setup_org_with_member(client)

    # Separate org, separate admin
    _, _, admin_b_token = await new_user(client)
    org_b_id = await new_org(client, admin_b_token)

    resp = await client.get(
        f"/api/v1/organizations/{org_b_id}/items",
        headers=auth_headers(member_token),
    )
    assert resp.status_code == 403


async def test_admin_of_org_a_cannot_access_org_b(client: AsyncClient) -> None:
    _, _, admin_a_token = await new_user(client)
    await new_org(client, admin_a_token)

    _, _, admin_b_token = await new_user(client)
    org_b_id = await new_org(client, admin_b_token)

    resp = await client.get(
        f"/api/v1/organizations/{org_b_id}/users",
        headers=auth_headers(admin_a_token),
    )
    assert resp.status_code == 403


async def test_items_are_isolated_between_orgs(client: AsyncClient) -> None:
    _, _, admin_a_token = await new_user(client)
    org_a_id = await new_org(client, admin_a_token)

    _, _, admin_b_token = await new_user(client)
    org_b_id = await new_org(client, admin_b_token)

    await create_item(client, admin_a_token, org_a_id, {"org": "A"})
    await create_item(client, admin_b_token, org_b_id, {"org": "B"})

    resp_a = await client.get(
        f"/api/v1/organizations/{org_a_id}/items",
        headers=auth_headers(admin_a_token),
    )
    resp_b = await client.get(
        f"/api/v1/organizations/{org_b_id}/items",
        headers=auth_headers(admin_b_token),
    )

    assert resp_a.json()["count"] == 1
    assert resp_a.json()["data"][0]["item_details"]["org"] == "A"
    assert resp_b.json()["count"] == 1
    assert resp_b.json()["data"][0]["item_details"]["org"] == "B"
