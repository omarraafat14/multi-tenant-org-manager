"""
Test infrastructure
===================

Dual-mode DB setup:

1. LOCAL / CI (default)
   Testcontainers spins up an isolated PostgreSQL container automatically.
   No external services required.

2. INSIDE DOCKER COMPOSE
   Set TEST_DATABASE_URL to point at the existing db service and we skip
   testcontainers entirely (container-in-container networking is unreliable).

   Example:
     docker compose exec \\
       -e TEST_DATABASE_URL=postgresql+psycopg_async://postgres:changethis@db:5432/app_test \\
       backend python -m pytest /app/backend/tests/ -v

   Create the test database first:
     docker compose exec db psql -U postgres -c "CREATE DATABASE app_test;"
"""
import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_db
from app.main import app

# ---------------------------------------------------------------------------
# DB URL — testcontainers (local) or injected URL (Docker)
# ---------------------------------------------------------------------------

_EXTERNAL_DB_URL: str | None = os.getenv("TEST_DATABASE_URL")


if _EXTERNAL_DB_URL:
    # ── Docker mode: use the provided URL directly ───────────────────────────
    @pytest.fixture(scope="session")
    def db_url() -> str:
        return _EXTERNAL_DB_URL  # type: ignore[return-value]

else:
    # ── Local mode: spin up a fresh PostgreSQL container ─────────────────────
    from testcontainers.postgres import PostgresContainer

    @pytest.fixture(scope="session")
    def pg():
        """PostgreSQL container — one per test session."""
        with PostgresContainer("postgres:15", driver="psycopg") as container:
            yield container

    @pytest.fixture(scope="session")
    def db_url(pg) -> str:  # type: ignore[misc]
        return pg.get_connection_url().replace(
            "postgresql+psycopg", "postgresql+psycopg_async"
        )


# ---------------------------------------------------------------------------
# Schema creation — runs once, shared across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_engine(db_url: str) -> Any:
    """
    Create all tables once and expose the shared engine.

    NullPool prevents connections from binding to a specific event loop,
    which is essential because pytest-asyncio uses a fresh loop per test.
    """
    container: dict[str, Any] = {}

    async def _setup() -> None:
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        container["engine"] = engine

    asyncio.run(_setup())
    yield container

    async def _teardown() -> None:
        await container["engine"].dispose()

    asyncio.run(_teardown())


# ---------------------------------------------------------------------------
# Per-test session + HTTP client
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def session(db_engine: dict) -> AsyncGenerator[AsyncSession, None]:
    """Fresh AsyncSession for every test function."""
    factory = async_sessionmaker(
        db_engine["engine"], class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as s:
        yield s


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client backed by the FastAPI app.
    get_db is overridden so every request uses the test session — keeping
    all DB state visible within a single test without extra commits.
    """
    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
