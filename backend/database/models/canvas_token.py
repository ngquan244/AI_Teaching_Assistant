"""
Canvas LMS access token storage with encryption at rest.
Supports multiple Canvas connections per user.
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


class TokenType(str, enum.Enum):
    """Type of Canvas access token."""
    PAT = "PAT"      # Personal Access Token (manually generated)
    OAUTH = "OAUTH"  # OAuth 2.0 token (via authorization flow)


class CanvasToken(Base):
    """
    Canvas LMS access token model.
    
    Security considerations:
    - access_token_encrypted is ALWAYS encrypted at rest
    - Tokens must NEVER appear in logs
    - Supports multiple Canvas domains per user
    - Soft-delete via revoked_at for audit trail
    """
    __tablename__ = "canvas_tokens"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique token identifier"
    )

    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner user ID"
    )

    # Canvas instance information
    canvas_domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Canvas LMS domain (e.g., https://canvas.instructure.com)"
    )

    # Encrypted access token
    access_token_encrypted: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="AES-256-GCM encrypted access token. NEVER log this value."
    )

    # Token metadata
    token_type: Mapped[TokenType] = mapped_column(
        SQLAlchemyEnum(TokenType, name="token_type", create_constraint=True),
        nullable=False,
        default=TokenType.PAT,
        comment="Token type (PAT or OAuth)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Token creation timestamp"
    )

    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last API call using this token"
    )

    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Revocation timestamp (soft delete)"
    )

    # Token label for user identification
    label: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="User-friendly label (e.g., 'Main Canvas Account')"
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="canvas_tokens"
    )

    # Indexes for common queries
    __table_args__ = (
        Index("ix_canvas_tokens_user_domain", "user_id", "canvas_domain"),
        Index("ix_canvas_tokens_active", "user_id", "revoked_at"),
        {"comment": "Encrypted Canvas LMS access tokens"}
    )

    def __repr__(self) -> str:
        # SECURITY: Never include token value in repr
        return f"<CanvasToken(id={self.id}, user_id={self.user_id}, domain={self.canvas_domain})>"

    @property
    def is_active(self) -> bool:
        """Check if token is not revoked."""
        return self.revoked_at is None

    def revoke(self) -> None:
        """Revoke this token (soft delete)."""
        self.revoked_at = datetime.now(timezone.utc)

    def update_last_used(self) -> None:
        """Update last used timestamp."""
        self.last_used_at = datetime.now(timezone.utc)
