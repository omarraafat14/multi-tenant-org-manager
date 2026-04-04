"""Shared test helpers — async API wrappers and random data generators."""
import random
import string

from httpx import AsyncClient, Response


# ---------------------------------------------------------------------------
# Random data generators
# ---------------------------------------------------------------------------

def random_email() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase, k=10))
    return f"user_{suffix}@testexample.com"


def random_password() -> str:
    """Always ≥ 8 chars, satisfies every password field validator in the app."""
    return "TestPass1!" + "".join(random.choices(string.ascii_lowercase, k=4))


# ---------------------------------------------------------------------------
# Auth header helper
# ---------------------------------------------------------------------------

def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# API wrappers
# ---------------------------------------------------------------------------

async def api_register(
    client: AsyncClient,
    *,
    email: str,
    password: str,
    full_name: str = "Test User",
) -> Response:
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


async def api_login(client: AsyncClient, *, email: str, password: str) -> str:
    """Login and return the raw JWT string."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


async def new_user(client: AsyncClient) -> tuple[str, str, str]:
    """
    Register a brand-new user with a random email.
    Returns (email, password, access_token).
    """
    email = random_email()
    password = random_password()
    resp = await api_register(client, email=email, password=password)
    assert resp.status_code == 200, f"Register failed: {resp.text}"
    return email, password, resp.json()["access_token"]


async def new_org(client: AsyncClient, token: str) -> str:
    """Create a new organisation and return its UUID string."""
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    resp = await client.post(
        "/api/v1/organizations/",
        json={"org_name": f"Org-{suffix}"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, f"Create org failed: {resp.text}"
    return resp.json()["id"]
