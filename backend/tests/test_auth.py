"""
Tests for section 2: Authentication
  - POST /auth/register
  - POST /auth/login
  - JWT enforcement on protected endpoints
"""
from httpx import AsyncClient

from tests.utils.utils import (
    api_login,
    api_register,
    auth_headers,
    new_user,
    random_email,
    random_password,
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def test_register_returns_bearer_token(client: AsyncClient) -> None:
    resp = await api_register(
        client, email=random_email(), password=random_password(), full_name="Alice"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


async def test_register_duplicate_email_is_400(client: AsyncClient) -> None:
    email = random_email()
    password = random_password()
    await api_register(client, email=email, password=password)

    resp = await api_register(client, email=email, password=password)
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"].lower()


async def test_register_password_too_short_is_422(client: AsyncClient) -> None:
    resp = await api_register(client, email=random_email(), password="short")
    assert resp.status_code == 422


async def test_register_invalid_email_is_422(client: AsyncClient) -> None:
    resp = await api_register(
        client, email="not-an-email", password=random_password()
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def test_login_correct_credentials_returns_token(client: AsyncClient) -> None:
    email, password, _ = await new_user(client)
    token = await api_login(client, email=email, password=password)
    assert isinstance(token, str)
    assert len(token) > 20  # JWTs are never tiny


async def test_login_wrong_password_is_400(client: AsyncClient) -> None:
    email, _, _ = await new_user(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPass99!"},
    )
    assert resp.status_code == 400


async def test_login_unknown_email_is_400(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": random_email(), "password": random_password()},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# JWT enforcement
# ---------------------------------------------------------------------------

async def test_missing_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/organizations/", json={"org_name": "X"})
    assert resp.status_code == 401


async def test_malformed_token_returns_401(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/organizations/",
        json={"org_name": "X"},
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert resp.status_code == 401


async def test_valid_token_grants_access(client: AsyncClient) -> None:
    _, _, token = await new_user(client)
    resp = await client.post(
        "/api/v1/organizations/",
        json={"org_name": "My Org"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201
