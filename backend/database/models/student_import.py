"""
Student-import batch models — durable preview/confirm state for the
Excel-based bulk-import / bulk-enroll flow.

Persisted in Postgres (NOT in-memory cache) so confirm survives worker
restart and works across multiple FastAPI instances.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User
    from .canvas_student import CanvasStudent


# ── Status / mode constants (kept as plain strings in DB) ───────────────────

class ImportMode:
    CREATE = "create"
    ENROLL = "enroll"


class BatchStatus:
    PREVIEW = "preview"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"


class RowStatus:
    # Common
    INVALID = "invalid"
    DUPLICATE_IN_FILE = "duplicate_in_file"
    SKIPPED = "skipped"
    FAILED = "failed"

    # Create-mode
    EXISTED_IN_DB = "existed_in_db"
    EXISTED_ON_CANVAS = "existed_on_canvas"
    SYNCED_FROM_CANVAS = "synced_from_canvas"
    VALID_NEW_USER = "valid_new_user"
    CREATED = "created"
    # Old account warnings (non-blocking; row is still create-eligible)
    OLD_ACCOUNT_EXISTS = "old_account_exists"   # old {MSSV}@vnu.edu.vn found on Canvas
    STALE_OLD_ACCOUNT = "stale_old_account"     # DB has entry with old email/no sv-prefix

    # Enroll-mode
    USER_NOT_FOUND_ON_CANVAS = "user_not_found_on_canvas"
    ENROLL_READY = "enroll_ready"
    ALREADY_ENROLLED = "already_enrolled"
    ENROLLMENT_INACTIVE = "enrollment_inactive"
    ENROLLMENT_COMPLETED = "enrollment_completed"
    ENROLLMENT_DELETED = "enrollment_deleted"
    ENROLLED = "enrolled"
    ENROLLMENT_FAILED = "enrollment_failed"


class StudentImportBatch(Base):
    """One uploaded Excel file → one batch with N rows."""

    __tablename__ = "student_import_batches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    canvas_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    course_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="create | enroll"
    )
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=BatchStatus.PREVIEW,
        comment="preview | confirmed | failed | expired",
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    enroll_after_create: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    enroll_existing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Preview is valid until this timestamp (default +24h)",
    )

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    rows: Mapped[list["StudentImportRow"]] = relationship(
        "StudentImportRow",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="StudentImportRow.row_number",
    )

    __table_args__ = (
        Index("ix_sib_owner_status", "owner_id", "status"),
        Index("ix_sib_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentImportBatch(id={self.id}, mode={self.mode}, "
            f"status={self.status}, rows={self.total_rows})>"
        )


class StudentImportRow(Base):
    """One row of an uploaded Excel — preview & post-confirm state."""

    __tablename__ = "student_import_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_import_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    row_number: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="1-based row number in the original file"
    )

    student_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    generated_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[str] = mapped_column(String(40), nullable=False)

    canvas_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    canvas_enrollment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    canvas_student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canvas_students.id", ondelete="SET NULL"),
        nullable=True,
    )
    sis_user_id_used: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # True iff this row triggered a fresh Canvas user creation in THIS batch.
    # Used to know whether `initial_password = "@<student_code>"` is still
    # valid to surface back to the operator (the password we just set on
    # Canvas).  Stays True even after the row.status moves on to "enrolled".
    created_in_this_batch: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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

    batch: Mapped["StudentImportBatch"] = relationship(
        "StudentImportBatch", back_populates="rows"
    )
    canvas_student: Mapped[Optional["CanvasStudent"]] = relationship(
        "CanvasStudent", foreign_keys=[canvas_student_id]
    )

    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_sir_batch_row"),
        Index("ix_sir_batch_status", "batch_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentImportRow(batch={self.batch_id}, row={self.row_number}, "
            f"code={self.student_code!r}, status={self.status})>"
        )
