"""
Invite Code and App Settings models.
Manages invite codes for controlled signup and runtime application settings.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


# =============================================================================
# App Settings — generic key-value store for runtime configuration
# =============================================================================

class AppSetting(Base):
    """
    Generic key-value runtime settings stored in DB.
    Multi-instance safe (all workers read from same source of truth).
    
    Example keys: SIGNUP_MODE
    """
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        comment="Setting key (e.g. SIGNUP_MODE)",
    )
    value: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default="null",
        comment="Setting value as JSON",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp",
    )

    __table_args__ = (
        {"comment": "Runtime application settings (key-value store)"},
    )

    def __repr__(self) -> str:
        return f"<AppSetting(key={self.key}, value={self.value})>"


# =============================================================================
# Invite Codes — managed invite codes for controlled signup
# =============================================================================

class InviteCode(Base):
    """
    Invite code for controlled user registration.
    
    Security:
    - code_hash stores HMAC-SHA256 of the plaintext code (never stored raw)
    - code_prefix stores first 6 chars for admin identification
    - Plaintext code is only returned once at creation time
    """
    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique invite code identifier",
    )
    code_hash: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
        comment="HMAC-SHA256 hash of the invite code",
    )
    code_prefix: Mapped[str] = mapped_column(
        String(6),
        nullable=False,
        comment="First 6 chars of plaintext code (for admin display)",
    )
    label: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Admin label/note (e.g. 'Lớp 10A')",
    )
    max_uses: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Max allowed uses (NULL = unlimited)",
    )
    used_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of times this code has been used",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this code is currently active",
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Expiration timestamp (NULL = never expires)",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Admin who created this code",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp",
    )

    # Relationships
    usages: Mapped[List["InviteCodeUsage"]] = relationship(
        "InviteCodeUsage",
        back_populates="invite_code",
        cascade="all, delete-orphan",
        lazy="noload",
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[created_by],
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_invite_codes_is_active", "is_active"),
        Index("ix_invite_codes_expires_at", "expires_at"),
        {"comment": "Invite codes for controlled user signup"},
    )

    def __repr__(self) -> str:
        return f"<InviteCode(id={self.id}, prefix={self.code_prefix}..., active={self.is_active})>"

    @property
    def is_expired(self) -> bool:
        """Check if this code has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_exhausted(self) -> bool:
        """Check if this code has reached its usage limit."""
        if self.max_uses is None:
            return False
        return self.used_count >= self.max_uses

    @property
    def is_usable(self) -> bool:
        """Check if this code can still be used."""
        return self.is_active and not self.is_expired and not self.is_exhausted


# =============================================================================
# Invite Code Usages — tracks who used which code
# =============================================================================

class InviteCodeUsage(Base):
    """
    Records each use of an invite code during signup.
    Provides audit trail and PII-minimal tracking.
    """
    __tablename__ = "invite_code_usages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Usage record identifier",
    )
    invite_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invite_codes.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK to invite code used",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="User who used this code to sign up",
    )
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the code was used",
    )

    # Relationships
    invite_code: Mapped["InviteCode"] = relationship(
        "InviteCode",
        back_populates="usages",
    )
    user: Mapped["User"] = relationship(
        "User",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_invite_code_usages_code_id", "invite_code_id"),
        Index("ix_invite_code_usages_user_id", "user_id"),
        {"comment": "Tracks invite code usage per user"},
    )

    def __repr__(self) -> str:
        return f"<InviteCodeUsage(code_id={self.invite_code_id}, user_id={self.user_id})>"
