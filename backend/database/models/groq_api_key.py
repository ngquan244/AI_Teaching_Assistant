"""
Groq API Key Pool model.
Manages multiple Groq API keys for load distribution and failover.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base


class GroqApiKey(Base):
    """
    A Groq API key in the rotation pool.

    Keys are encrypted at rest via Fernet (same as the legacy single-key
    stored in ``AppSetting``).  The pool manager rotates through enabled
    keys in round-robin order, skipping any that have accumulated too
    many consecutive errors.
    """

    __tablename__ = "groq_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        comment="Human-friendly label (e.g. 'Key A – free tier')",
    )
    encrypted_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Fernet-encrypted API key",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Admin toggle – disabled keys are skipped by the pool",
    )
    error_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive error counter (reset on success)",
    )
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of most recent API error",
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp of most recent successful use",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        {"comment": "Pool of Groq API keys for quiz generation load distribution"},
    )

    def __repr__(self) -> str:
        return f"<GroqApiKey(id={self.id}, name={self.name!r}, enabled={self.enabled})>"
