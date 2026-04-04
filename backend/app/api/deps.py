import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models import Membership, Role, TokenPayload, User

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    user = await session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


# ---------------------------------------------------------------------------
# Organization RBAC dependencies
# ---------------------------------------------------------------------------

async def get_org_membership(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Membership:
    """
    Resolve the calling user's membership in `org_id`.
    Raises 403 if the user is not a member.
    """
    result = await session.exec(
        select(Membership).where(
            Membership.org_id == org_id,
            Membership.user_id == current_user.id,
        )
    )
    membership = result.first()
    print(f"Membership for user {current_user.id} in org {org_id}: {membership}")
    if not membership:
        raise HTTPException(
            status_code=403, detail="You are not a member of this organization"
        )
    return membership


async def require_admin(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: SessionDep,
) -> Membership:
    """
    Like `get_org_membership` but additionally requires Role.ADMIN.
    Raises 403 for non-members and for members without admin role.
    """
    membership = await get_org_membership(
        org_id=org_id, current_user=current_user, session=session
    )
    if membership.role != Role.ADMIN:
        raise HTTPException(
            status_code=403, detail="Admin privileges required"
        )
    return membership
