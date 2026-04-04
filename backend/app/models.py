import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Enum as SAEnum, JSON
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    memberships: list["Membership"] = Relationship(back_populates="user", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


###########################################
class Role(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

#  Organization 
class Organization(SQLModel, table=True):
    """Database model for organization, database table inferred from class name"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_name: str = Field(max_length=255)
    created_at : datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # Relationships
    memberships: list["Membership"] = Relationship(back_populates="organization", cascade_delete=True)
    items: list["Item"] = Relationship(back_populates="organization", cascade_delete=True)
    audit_logs: list["AuditLog"] = Relationship(back_populates="organization", cascade_delete=True)

class OrganizationCreate(SQLModel):
    """Used when creating an organization (API input)"""
    org_name: str = Field(min_length=1, max_length=255)

class OrganizationPublic(SQLModel):
    """Used when returning organization data via API (API output)"""
    id: uuid.UUID
    org_name: str
    created_at: datetime | None = None

###########################################
# Membership 
class Membership(SQLModel, table=True):
    """Database model for membership, database table inferred from class name"""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", nullable=False, ondelete="CASCADE", index=True)
    role: Role = Field(
        default=Role.MEMBER,
        sa_column=Column(
            SAEnum(Role, values_callable=lambda x: [e.value for e in x], name="role"),
            nullable=False,
        ),
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    # Relationships
    user: User | None = Relationship(back_populates="memberships")
    organization: Organization | None = Relationship(back_populates="memberships")

class MembershipPublic(SQLModel):
    """Used when returning membership data via API (API output)"""
    id: uuid.UUID
    user_id: uuid.UUID
    org_id: uuid.UUID
    role: Role
    created_at: datetime | None = None

class InviteUser(SQLModel):
    email: EmailStr
    role: Role = Role.MEMBER

class MemberSearchResult(SQLModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None = None
    role: Role
    member_since: datetime | None = None

###########################################
# Item

class ItemCreate(SQLModel):
    item_details: dict[str, Any]


class ItemUpdate(SQLModel):
    item_details: dict[str, Any] | None = None


class Item(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    item_details: dict[str, Any] = Field(sa_type=JSON)  # type: ignore
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    org_id: uuid.UUID = Field(
        foreign_key="organization.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")
    organization: Organization | None = Relationship(back_populates="items")


class ItemPublic(SQLModel):
    id: uuid.UUID
    item_details: dict[str, Any]
    owner_id: uuid.UUID | None
    org_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int

###########################################
# AuditLog 
class AuditLog(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organization.id", ondelete="CASCADE", index=True)
    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL", nullable=True
    )
    action: str = Field(max_length=500)
    details: dict[str, Any] | None = Field(default=None, sa_type=JSON)  # type: ignore
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    organization: Organization | None = Relationship(back_populates="audit_logs")


class AuditLogPublic(SQLModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    details: dict[str, Any] | None
    created_at: datetime | None

class AuditLogsPublic(SQLModel):
    data: list[AuditLogPublic]
    count: int


# Auth request schemas
class LoginRequest(SQLModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

