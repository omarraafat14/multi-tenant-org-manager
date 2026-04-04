import uuid
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.security import get_password_hash, verify_password
from app.models import (
    AuditLog,
    Item,
    ItemCreate,
    Membership,
    Organization,
    OrganizationCreate,
    Role,
    User,
    UserCreate,
    UserUpdate,
)


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

async def create_user(*, session: AsyncSession, user_create: UserCreate) -> User:
    db_obj = User.model_validate(
        user_create, update={"hashed_password": get_password_hash(user_create.password)}
    )
    session.add(db_obj)
    await session.commit()
    await session.refresh(db_obj)
    return db_obj


async def update_user(*, session: AsyncSession, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    await session.commit()
    await session.refresh(db_user)
    return db_user


async def get_user_by_email(*, session: AsyncSession, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    result = await session.exec(statement)
    return result.first()


async def authenticate(*, session: AsyncSession, email: str, password: str) -> User | None:
    db_user = await get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        await session.commit()
        await session.refresh(db_user)
    return db_user


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

async def get_membership(
    *, session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> Membership | None:
    result = await session.exec(
        select(Membership).where(
            Membership.org_id == org_id,
            Membership.user_id == user_id,
        )
    )
    return result.first()


async def log_action(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID | None,
    action: str,
    details: dict | None = None,
) -> AuditLog:
    """Insert a single audit log entry and commit."""
    audit = AuditLog(org_id=org_id, user_id=user_id, action=action, details=details)
    session.add(audit)
    await session.commit()
    await session.refresh(audit)
    return audit


async def create_organization(
    *, session: AsyncSession, org_in: OrganizationCreate, owner_id: uuid.UUID
) -> Organization:
    """
    Create an organization, grant the caller ADMIN membership, and emit an
    audit log entry — all in a single transaction.
    """
    org = Organization(org_name=org_in.org_name)
    session.add(org)
    await session.flush()  # populate org.id before referencing it in children

    membership = Membership(user_id=owner_id, org_id=org.id, role=Role.ADMIN)
    session.add(membership)

    audit = AuditLog(
        org_id=org.id,
        user_id=owner_id,
        action="organization_created",
        details={"org_name": org.org_name, "created_by": str(owner_id)},
    )
    session.add(audit)

    await session.commit()
    await session.refresh(org)
    return org


async def invite_user_to_org(
    *,
    session: AsyncSession,
    org_id: uuid.UUID,
    inviter_id: uuid.UUID,
    email: str,
    role: Role = Role.MEMBER,
) -> Membership:
    """
    Look up a user by email and add them to the organization.
    Raises ValueError for unknown email or duplicate membership.
    """
    user = await get_user_by_email(session=session, email=email)
    if not user:
        raise ValueError(f"No user found with email '{email}'")

    existing = await get_membership(session=session, org_id=org_id, user_id=user.id)
    if existing:
        raise ValueError("User is already a member of this organization")

    membership = Membership(user_id=user.id, org_id=org_id, role=role)
    session.add(membership)

    audit = AuditLog(
        org_id=org_id,
        user_id=inviter_id,
        action="user_invited",
        details={"email": email, "role": role, "invited_by": str(inviter_id)},
    )
    session.add(audit)

    await session.commit()
    await session.refresh(membership)
    return membership


# ---------------------------------------------------------------------------
# Item
# ---------------------------------------------------------------------------

async def create_item(
    *,
    session: AsyncSession,
    item_in: ItemCreate,
    org_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> Item:
    """Create an item inside an org and log the action."""
    item = Item.model_validate(item_in, update={"org_id": org_id, "owner_id": owner_id})
    session.add(item)
    await session.flush()  # populate item.id

    audit = AuditLog(
        org_id=org_id,
        user_id=owner_id,
        action="item_created",
        details={"item_id": str(item.id)},
    )
    session.add(audit)

    await session.commit()
    await session.refresh(item)
    return item
