"""
Guide Document model.
Stores per-panel user guide documents with markdown content.
Each document corresponds to a panel/feature and can be edited independently.
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
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base


class GuideDocument(Base):
    """
    A single guide document tied to a panel/feature.

    Each panel (chat, upload, grading, etc.) can have its own guide document
    with independent markdown content, editable by admins.
    Images are stored as URLs pointing to /media/guide/{filename}.
    """
    __tablename__ = "guide_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique guide document identifier",
    )
    panel_key: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="Panel key matching ALL_PANELS (e.g. 'chat', 'upload', 'grading')",
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Display title (e.g. 'Chat AI', 'Upload bài thi')",
    )
    description: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Short description shown on overview cards",
    )
    icon_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Lucide icon name (e.g. 'MessageSquare', 'Upload')",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        comment="Markdown content of the guide document",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order (lower = first)",
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this guide is visible to users",
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

    __table_args__ = (
        Index("ix_guide_documents_panel_key", "panel_key"),
        Index("ix_guide_documents_sort_order", "sort_order"),
        {"comment": "Per-panel user guide documents with markdown content"},
    )

    def __repr__(self) -> str:
        return f"<GuideDocument(panel_key={self.panel_key}, title={self.title})>"
