"""
User model with role-based access control.
Designed for PostgreSQL with proper ENUMs, indexes, and constraints.
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    String,
    DateTime,
    Enum as SQLAlchemyEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .canvas_token import CanvasToken


class UserRole(str, enum.Enum):
    """User role enumeration for RBAC."""
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"


class UserStatus(str, enum.Enum):
    """User account status enumeration."""
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    PENDING = "PENDING"


class User(Base):
    """
    User model representing authenticated users in the system.
    
    Security considerations:
    - password_hash is nullable to support future OAuth-only users
    - Passwords are NEVER stored in plaintext
    - Email is unique and indexed for fast lookups
    - All timestamps are timezone-aware (UTC)
    """
    __tablename__ = "users"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique user identifier"
    )

    # Core user information
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="User email address (unique, used for login)"
    )
    
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="User display name"
    )

    # Role and status
    role: Mapped[UserRole] = mapped_column(
        SQLAlchemyEnum(UserRole, name="user_role", create_constraint=True),
        nullable=False,
        default=UserRole.TEACHER,
        comment="User role for access control"
    )
    
    status: Mapped[UserStatus] = mapped_column(
        SQLAlchemyEnum(UserStatus, name="user_status", create_constraint=True),
        nullable=False,
        default=UserStatus.ACTIVE,
        comment="Account status"
    )

    # Authentication - nullable to support OAuth-only users
    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Hashed password (bcrypt/argon2). NULL for OAuth-only users."
    )

    # Timestamps (all timezone-aware UTC)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Account creation timestamp"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp"
    )
    
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful login timestamp"
    )

    # Relationships
    canvas_tokens: Mapped[List["CanvasToken"]] = relationship(
        "CanvasToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
        Index("ix_users_role", "role"),
        {"comment": "User accounts with role-based access control"}
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"

    @property
    def is_active(self) -> bool:
        """Check if user account is active."""
        return self.status == UserStatus.ACTIVE

    @property
    def is_admin(self) -> bool:
        """Check if user has admin privileges."""
        return self.role == UserRole.ADMIN
