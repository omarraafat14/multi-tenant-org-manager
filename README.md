# Multi-Tenant Organization Manager

A production-ready multi-tenant backend built with **FastAPI**, **async SQLAlchemy 2.0**, and **PostgreSQL**. Organisations are fully isolated — members can only access data within their own organisation, and role-based access control (RBAC) is enforced at the API layer.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Data Model](#data-model)
- [API Reference](#api-reference)
- [How to Run Locally](#how-to-run-locally)
- [Running Tests](#running-tests)
- [Design Decisions & Tradeoffs](#design-decisions--tradeoffs)
- [Project Structure](#project-structure)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                        Clients                          │
│                  (curl / tests / apps)                  │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────────┐
│                   Traefik (proxy)                       │
│          TLS termination · routing · redirect           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              FastAPI  (port 8000)                       │
│                                                         │
│  /api/v1/auth/*          ← JSON register / login        │
│  /api/v1/organizations/* ← RBAC org + item endpoints    │
│  /api/v1/users/*         ← user profile management      │
│  /api/v1/utils/*         ← health-check                 │
│                                                         │
│  Async SQLAlchemy 2.0 · SQLModel · Pydantic v2          │
│  JWT auth · bcrypt/argon2 password hashing              │
└──────────────────────┬──────────────────────────────────┘
                       │ psycopg (async)
┌──────────────────────▼──────────────────────────────────┐
│                  PostgreSQL 18                          │
│                                                         │
│  user · organization · membership · item · auditlog     │
│  GIN index for full-text member search                  │
│  Alembic migrations                                     │
└─────────────────────────────────────────────────────────┘
```

---

## Data Model

```
user
├── id          UUID PK
├── email       unique, FTS-indexed
├── full_name
├── hashed_password
├── is_active / is_superuser
└── created_at

organization
├── id          UUID PK
├── org_name
└── created_at

membership  (user ↔ organisation, many-to-many with role)
├── id
├── user_id     FK → user   ON DELETE CASCADE
├── org_id      FK → org    ON DELETE CASCADE
├── role        ENUM('admin', 'member')
└── created_at

item  (org-scoped; owner nullable so items survive user deletion)
├── id
├── item_details  JSONB      ← flexible schema
├── org_id        FK → org   ON DELETE CASCADE
├── owner_id      FK → user  ON DELETE SET NULL (nullable)
└── created_at

auditlog
├── id
├── org_id      FK → org    ON DELETE CASCADE
├── user_id     FK → user   ON DELETE SET NULL (nullable)
├── action      varchar
├── details     JSONB
└── created_at
```

### GIN index for full-text search

```sql
CREATE INDEX ix_user_fts ON "user"
  USING GIN (to_tsvector('english',
    coalesce(full_name, '') || ' ' || email));
```

Enables prefix-matching search (`john:* & sm:*`) across member names and emails with no external search service.

---

## API Reference

All endpoints are prefixed with `/api/v1`.

### Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/register` | — | Create account, returns JWT |
| `POST` | `/auth/login` | — | JSON login, returns JWT |
| `POST` | `/login/access-token` | — | OAuth2 form login (Swagger UI) |
| `POST` | `/password-recovery/{email}` | — | Send password reset email |
| `POST` | `/reset-password/` | — | Set new password via reset token |

### Organizations

| Method | Path | Role | Description |
|--------|------|------|-------------|
| `POST` | `/organizations/` | any user | Create org — caller becomes admin |
| `POST` | `/{org_id}/users` | admin | Invite an existing user by email |
| `GET` | `/{org_id}/users` | admin | List all members |
| `GET` | `/{org_id}/users/search?q=` | admin | Full-text search members (prefix) |
| `POST` | `/{org_id}/items` | member / admin | Create an item |
| `GET` | `/{org_id}/items` | member / admin | List items (members see own; admins see all) |
| `GET` | `/{org_id}/audit-logs` | admin | Paginated audit log |
| `POST` | `/{org_id}/audit-logs/ask` | admin | AI chatbot — ask about today's audit activity |

### Users

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/users/me` | self | Get own profile |
| `PATCH` | `/users/me` | self | Update own profile |
| `PATCH` | `/users/me/password` | self | Change password |
| `DELETE` | `/users/me` | self | Delete own account |
| `GET` | `/users/` | superuser | List all users |
| `POST` | `/users/` | superuser | Create user |
| `GET` | `/users/{user_id}` | superuser | Get user by ID |
| `PATCH` | `/users/{user_id}` | superuser | Update user |
| `DELETE` | `/users/{user_id}` | superuser | Delete user |

---

## How to Run Locally

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/)
- (Optional) Python 3.11+ for running tests outside Docker

### 1. Clone and configure

```bash
git clone <repo-url>
cd multi-tenant-org-manager
cp .env.example .env   # or edit .env directly
```

Key `.env` variables:

```ini
POSTGRES_PASSWORD=changethis     # change before any real deployment
SECRET_KEY=changethis            # generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=changethis
LLM_API_KEY=                     # optional — Gemini key for the AI chatbot endpoint
```

### 2. Start all services

```bash
docker compose up --build
```

This starts:

| Service | URL | Description |
|---------|-----|-------------|
| **backend** | http://localhost:8000 | FastAPI app (hot-reload) |
| **db** | localhost:5432 | PostgreSQL 18 |
| **adminer** | http://localhost:8080 | DB browser UI |
| **mailcatcher** | http://localhost:1080 | Catch outgoing emails |

The `prestart` service runs automatically before the backend starts — it applies Alembic migrations and seeds the first superuser.

### 3. Explore the API

- Interactive docs (Swagger UI): http://localhost:8000/docs
- Alternative docs (ReDoc): http://localhost:8000/redoc
- Health check: http://localhost:8000/api/v1/utils/health-check/

### 4. Quick API walkthrough

```bash
BASE=http://localhost:8000/api/v1

# Register a user
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Secret123!","full_name":"Alice"}' | jq .

# Login
TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Secret123!"}' | jq -r .access_token)

# Create an organisation
ORG=$(curl -s -X POST $BASE/organizations/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"org_name":"Acme Corp"}' | jq -r .id)

# Create an item
curl -s -X POST $BASE/organizations/$ORG/items \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"item_details":{"title":"Q1 Report","status":"draft"}}' | jq .

# View audit log
curl -s $BASE/organizations/$ORG/audit-logs \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

## Running Tests

Tests use **pytest-asyncio** and **testcontainers** (Postgres). Two modes are supported:

### Docker mode (recommended — no local Python setup needed)

```bash
# Create the test database once
docker compose exec db psql -U postgres -c "CREATE DATABASE app_test;"

# Run the full test suite
docker compose exec \
  -e TEST_DATABASE_URL=postgresql+psycopg_async://postgres:changethis@db:5432/app_test \
  backend bash -c "cd /app/backend && python -m pytest tests/ -v --asyncio-mode=auto"
```

### Local mode (testcontainers auto-provisions Postgres)

Requires Docker to be running (testcontainers spawns its own Postgres container):

```bash
cd backend
pip install -e ".[dev]"          # or: uv sync --group dev
pytest tests/ -v
```

### Test coverage

```
tests/test_auth.py           10 tests
  ├── register: success, duplicate email, short password, invalid email
  └── login: success, wrong password, unknown email, missing/malformed/valid JWT

tests/test_organizations.py  15 tests
  ├── org creation: creator becomes admin, audit log emitted
  ├── RBAC — member restrictions: cannot invite, list members, view audit logs
  ├── RBAC — admin capabilities: invite user, see all items, view audit logs
  ├── edge cases: invite unknown email → 400, invite duplicate → 400
  └── org isolation: non-member blocked, cross-org access blocked, items isolated
```

---

## Design Decisions & Tradeoffs

### Async SQLAlchemy 2.0 over sync ORM

**Decision:** All database access uses `async_sessionmaker` + `AsyncSession` with `psycopg` (v3) async driver.

**Why:** FastAPI is built on Starlette's async event loop. Sync ORM calls block the loop, meaning one slow query prevents all other requests from being served. Async I/O allows thousands of concurrent requests with a small thread pool.

**Tradeoff:** Async SQLAlchemy has sharper edges — lazy-loaded relationships silently fail, and `session.exec()` (SQLModel) vs `session.execute()` (SQLAlchemy) behave differently for joins. Multi-column joins that return non-model rows require `session.execute()` with `.mappings()`. This added some complexity to the FTS search endpoint.

---

### NullPool for test sessions

**Decision:** The test engine is created with `poolclass=NullPool`.

**Why:** pytest-asyncio creates a new event loop per test function. A connection pool binds connections to the event loop that created them — reusing a pooled connection on a different loop raises `RuntimeError`. `NullPool` opens and closes a fresh connection per request, which is slower but loop-safe.

**Tradeoff:** Slightly slower tests (no connection reuse), but correct behaviour across all test isolation levels.

---

### Shared schema, scoped queries (vs separate schemas per tenant)

**Decision:** All organisations share the same PostgreSQL tables. Every query filters by `org_id`.

**Why:** A separate-schema or separate-database approach (full tenant isolation at the DB level) requires dynamic connection routing, per-tenant migration runs, and complicates connection pooling. For most multi-tenant SaaS applications the operational overhead outweighs the benefits until scale demands it.

**Tradeoff:** A bug that omits a `.where(org_id == ...)` filter could leak data across tenants. This is mitigated by centralising all data access through CRUD functions and RBAC FastAPI dependencies, so raw queries never appear in route handlers.

---

### RBAC via FastAPI dependency injection

**Decision:** RBAC is enforced through two reusable dependencies — `get_org_membership` (any member) and `require_admin` (admin only) — injected directly into route signatures.

```python
@router.post("/{org_id}/users")
async def invite_user(
    ...,
    _: Membership = Depends(require_admin),   # ← enforced here
):
```

**Why:** Dependencies run before the handler body. There is no way to accidentally skip the check — if `require_admin` raises, FastAPI short-circuits with 403 before the handler runs. Tests confirmed all 403/404 paths without any mocking.

**Tradeoff:** Fine-grained permissions (e.g., role hierarchy, per-resource ACLs) would require a more expressive permission model. For this two-role system (admin / member) the dependency approach is simple and self-documenting.

---

### Flexible `item_details: JSONB` instead of fixed columns

**Decision:** `Item` stores a single `item_details JSONB` column instead of predefined `title` / `description` columns.

**Why:** Different organisations may attach entirely different metadata to items. A fixed schema would require a migration for every new field requirement. JSONB preserves the flexibility of a document store while staying inside PostgreSQL (no extra service, full ACID guarantees, indexable with GIN if needed later).

**Tradeoff:** No column-level constraints or indexing on the contents by default. Application code must validate the shape of `item_details` at the API boundary (done via `dict[str, Any]` in Pydantic — any JSON object is accepted).

---

### PostgreSQL full-text search with GIN index

**Decision:** Member search uses `to_tsvector` / `to_tsquery` with a GIN index rather than `ILIKE` or an external search engine.

**Why:** `ILIKE '%term%'` requires a full table scan. A GIN index on the tsvector of `full_name || ' ' || email` makes prefix-match searches (`john:*`) fast at any table size, with zero infrastructure beyond what's already running.

**Tradeoff:** FTS is English-stemmed, so language-specific edge cases (e.g. searching for "running" matching "run") may behave unexpectedly. `ILIKE` is simpler to reason about for exact substring matches. For an international user base, a `pg_trgm` trigram index might be more appropriate.

---

### Audit log in the same transaction as the triggering action

**Decision:** `log_action()` is called inside the same database transaction as the operation it records (using `session.flush()` to get IDs, then a single `session.commit()`).

**Why:** An audit log that can succeed while the action fails (or vice versa) is unreliable. Keeping them in one transaction means either both land or neither does.

**Tradeoff:** Slightly larger transactions. For high-throughput writes, decoupling the audit log to an async queue (e.g. Kafka, Redis Streams) would improve write latency at the cost of eventual-consistency guarantees on the audit trail.

---

### Dual-mode test database (testcontainers + external URL)

**Decision:** `conftest.py` checks `TEST_DATABASE_URL`. If set, it uses that URL directly; otherwise it spins up a fresh Postgres container via testcontainers.

**Why:** Running testcontainers inside Docker Compose (container-in-container) is unreliable — the spawned Postgres container maps a port on the Docker host, but the backend container is on a bridge network and cannot reach `172.17.0.x`. The dual-mode approach gives clean local/CI execution (testcontainers) and reliable Docker Compose execution (existing `db` service + `app_test` database).

**Tradeoff:** Tests do not truncate between runs in Docker mode (the `app_test` DB accumulates data). Because every test creates users and organisations with randomised emails and IDs, cross-contamination is avoided in practice — but a long-running `app_test` DB may grow large over many test runs.

---

## Project Structure

```
.
├── compose.yml                  # Docker Compose (all services)
├── .env                         # Environment config (copy from .env.example)
│
└── backend/
    ├── Dockerfile
    ├── pyproject.toml           # Dependencies + pytest config
    ├── alembic.ini
    │
    ├── app/
    │   ├── main.py              # FastAPI app entrypoint
    │   ├── models.py            # All SQLModel table + Pydantic schema definitions
    │   ├── crud.py              # Async DB operations (no raw SQL in routes)
    │   │
    │   ├── api/
    │   │   ├── deps.py          # get_db, get_current_user, require_admin, get_org_membership
    │   │   ├── main.py          # Router registration
    │   │   └── routes/
    │   │       ├── auth.py      # /auth/register, /auth/login, OAuth2 form login
    │   │       ├── organizations.py  # All org / member / item / audit endpoints
    │   │       ├── users.py     # User self-management + superuser CRUD
    │   │       └── utils.py     # Health check
    │   │
    │   ├── core/
    │   │   ├── config.py        # Pydantic Settings (reads .env)
    │   │   ├── db.py            # Async engine + AsyncSessionLocal + init_db
    │   │   └── security.py      # JWT creation, password hashing
    │   │
    │   └── alembic/
    │       └── versions/
    │           ├── 578553d2161a_initial.py              # Base schema
    │           ├── c1d2e3f4a5b6_add_user_fts_gin_index.py
    │           └── d2e3f4a5b6c7_replace_item_..._json.py
    │
    └── tests/
        ├── conftest.py          # Dual-mode DB setup, async session + client fixtures
        ├── test_auth.py         # 10 authentication tests
        ├── test_organizations.py # 15 RBAC + isolation tests
        └── utils/
            └── utils.py         # random_email, api_register, new_user, new_org helpers
```
