"""
Canvas Student models — production-grade mirror of Canvas users + enrollments.

Distinct from `test_students` (which is reserved for quiz-attempt simulation).
Used by the Excel-based bulk import / enroll flow.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


class CanvasStudent(Base):
    """
    A Canvas user (student role) mirrored locally.

    Source of truth is Canvas; this row is a cache for fast lookup,
    dedupe and joining with enrollments. Many `CanvasStudentEnrollment`
    rows can attach to one `CanvasStudent` (one student can be in many
    courses).
    """
    __tablename__ = "canvas_students"

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
        comment="App user who first synced/imported this Canvas student",
    )

    canvas_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    canvas_user_id: Mapped[int] = mapped_column(Integer, nullable=False)

    student_code: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="MSSV — derived from sis_user_id or login_id"
    )
    sis_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    login_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="excel_import",
        comment="excel_import | synced_from_canvas | manual",
    )

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    enrollments: Mapped[list["CanvasStudentEnrollment"]] = relationship(
        "CanvasStudentEnrollment",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "canvas_domain", "canvas_user_id", name="uq_canvas_students_domain_user"
        ),
        Index("ix_canvas_students_owner_domain", "owner_id", "canvas_domain"),
        Index("ix_canvas_students_email", "canvas_domain", "email"),
        # Partial unique on (canvas_domain, student_code) is created in migration
        # because SQLAlchemy can't express PG WHERE clause portably.
        {"comment": "Mirror of Canvas student users for production import/enroll"},
    )

    def __repr__(self) -> str:
        return (
            f"<CanvasStudent(id={self.id}, canvas_user_id={self.canvas_user_id}, "
            f"code={self.student_code!r})>"
        )


class CanvasStudentEnrollment(Base):
    """
    Mirror of one Canvas enrollment record (student in a course).

    Many enrollments per student (multi-course). Authoritative state lives on
    Canvas; we cache the latest known state for fast pre-checks.
    """
    __tablename__ = "canvas_student_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    canvas_student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("canvas_students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    canvas_domain: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Denormalized for query convenience"
    )
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    canvas_enrollment_id: Mapped[int] = mapped_column(Integer, nullable=False)

    enrollment_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="StudentEnrollment"
    )
    enrollment_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="active | invited | inactive | completed | deleted",
    )

    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
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

    student: Mapped["CanvasStudent"] = relationship(
        "CanvasStudent", back_populates="enrollments"
    )

    __table_args__ = (
        UniqueConstraint(
            "canvas_domain",
            "canvas_enrollment_id",
            name="uq_cse_domain_enrollment",
        ),
        Index("ix_cse_student_course", "canvas_student_id", "course_id"),
        Index(
            "ix_cse_course_state",
            "canvas_domain",
            "course_id",
            "enrollment_state",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CanvasStudentEnrollment(id={self.id}, course_id={self.course_id}, "
            f"state={self.enrollment_state})>"
        )
