import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select as sa_select, text
from sqlmodel import col, func, select

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_org_membership, require_admin
from app.models import (
    AuditLog,
    AuditLogPublic,
    AuditLogsPublic,
    InviteUser,
    Item,
    ItemCreate,
    ItemPublic,
    ItemsPublic,
    Membership,
    MembershipPublic,
    MemberSearchResult,
    Organization,
    OrganizationCreate,
    OrganizationPublic,
    Role,
    User,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

@router.post("/", response_model=OrganizationPublic, status_code=201)
async def create_organization(
    body: OrganizationCreate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Organization:
    """
    Create a new organization.
    The authenticated user becomes its first ADMIN automatically.
    """
    return await crud.create_organization(
        session=session, org_in=body, owner_id=current_user.id
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.post("/{org_id}/users", response_model=MembershipPublic, status_code=201)
async def invite_user(
    org_id: uuid.UUID,
    body: InviteUser,
    session: SessionDep,
    current_user: CurrentUser,
    _: Membership = Depends(require_admin),
) -> Membership:
    """
    Invite an existing user to the organization by email (admin only).
    The role defaults to MEMBER but can be set to ADMIN.
    """
    try:
        return await crud.invite_user_to_org(
            session=session,
            org_id=org_id,
            inviter_id=current_user.id,
            email=body.email,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{org_id}/users/search", response_model=list[MemberSearchResult])
async def search_members(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Membership = Depends(require_admin),
    q: str = Query(..., min_length=1, description="Full-text search query (names or emails)"),
) -> list[MemberSearchResult]:
    """
    Full-text search over member names and emails (admin only).

    Uses PostgreSQL tsvector/tsquery with a GIN index for performance.
    Each word in `q` is matched as a prefix, so `jo` matches `john`.
    Returns user details + role for every matching member.
    """
    # Strip tsquery special chars to prevent syntax errors, then build prefix query.
    # e.g. "john do" → "john:* & do:*"
    safe_q = re.sub(r"[^\w\s]", "", q, flags=re.UNICODE).strip()
    if not safe_q:
        return []
    tsquery = " & ".join(f"{word}:*" for word in safe_q.split())

    stmt = (
        sa_select(
            User.id.label("user_id"),
            User.email,
            User.full_name,
            Membership.role,
            Membership.created_at.label("member_since"),
        )
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.org_id == org_id)
        .where(
            text(
                "to_tsvector('english', coalesce(\"user\".full_name, '') || ' ' || \"user\".email)"
                " @@ to_tsquery('english', :tsquery)"
            ).bindparams(tsquery=tsquery)
        )
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [MemberSearchResult.model_validate(dict(row)) for row in rows]


@router.get("/{org_id}/users", response_model=list[MembershipPublic])
async def list_members(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Membership = Depends(require_admin),
    skip: int = 0,
    limit: int = 100,
) -> list[Membership]:
    """List all members of the organization (admin only)."""
    result = await session.exec(
        select(Membership)
        .where(Membership.org_id == org_id)
        .offset(skip)
        .limit(limit)
    )
    return list(result.all())


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

@router.post("/{org_id}/items", response_model=ItemPublic, status_code=201)
async def create_item(
    org_id: uuid.UUID,
    body: ItemCreate,
    session: SessionDep,
    current_user: CurrentUser,
    _: Membership = Depends(get_org_membership),
) -> Item:
    """Create an item inside the organization (any member)."""
    return await crud.create_item(
        session=session, item_in=body, org_id=org_id, owner_id=current_user.id
    )


@router.get("/{org_id}/items", response_model=ItemsPublic)
async def list_items(
    org_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    membership: Membership = Depends(get_org_membership),
    skip: int = 0,
    limit: int = 100,
) -> ItemsPublic:
    """
    List items in the organization.
    - **Admins** see every item.
    - **Members** see only items they created.
    """
    base_filter = [Item.org_id == org_id]
    if membership.role != Role.ADMIN:
        base_filter.append(Item.owner_id == current_user.id)

    count_stmt = select(func.count()).select_from(Item).where(*base_filter)
    count = (await session.exec(count_stmt)).one()

    items_stmt = (
        select(Item)
        .where(*base_filter)
        .order_by(col(Item.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    items = (await session.exec(items_stmt)).all()

    return ItemsPublic(
        data=[ItemPublic.model_validate(item) for item in items],
        count=count,
    )


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------

@router.get("/{org_id}/audit-logs", response_model=AuditLogsPublic)
async def list_audit_logs(
    org_id: uuid.UUID,
    session: SessionDep,
    _: Membership = Depends(require_admin),
    skip: int = 0,
    limit: int = 100,
) -> AuditLogsPublic:
    """Return paginated audit log entries for the organization (admin only)."""
    count_stmt = (
        select(func.count()).select_from(AuditLog).where(AuditLog.org_id == org_id)
    )
    count = (await session.exec(count_stmt)).one()

    logs_stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == org_id)
        .order_by(col(AuditLog.created_at).desc())
        .offset(skip)
        .limit(limit)
    )
    logs = (await session.exec(logs_stmt)).all()

    return AuditLogsPublic(
        data=[AuditLogPublic.model_validate(log) for log in logs],
        count=count,
    )
