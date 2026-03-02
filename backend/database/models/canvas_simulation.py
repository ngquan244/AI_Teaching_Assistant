"""
Canvas simulation-related models: test students, simulation runs, and audit log.
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


# ── Enums ─────────────────────────────────────────────────────────────────

class TestStudentStatus(str, enum.Enum):
    """Lifecycle state of a test student account on Canvas."""
    ACTIVE = "active"
    ENROLLED = "enrolled"
    UNENROLLED = "unenrolled"
    DELETED = "deleted"
    ERROR = "error"


class SimulationStatus(str, enum.Enum):
    """Status of a simulation run."""
    PENDING = "pending"
    ENROLLING = "enrolling"
    SUBMITTING = "submitting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class AuditAction(str, enum.Enum):
    """Types of auditable Canvas mutation actions."""
    CREATE_USER = "create_user"
    ENROLL_USER = "enroll_user"
    UNENROLL_USER = "unenroll_user"
    START_SUBMISSION = "start_submission"
    ANSWER_QUESTIONS = "answer_questions"
    COMPLETE_SUBMISSION = "complete_submission"
    DELETE_USER = "delete_user"


# ── Models ────────────────────────────────────────────────────────────────

class TestStudent(Base):
    """
    A Canvas user account created for simulation purposes.
    Tracks the canvas_user_id so we can re-use / clean up later.
    """
    __tablename__ = "test_students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Internal PK",
    )

    # Who created this test student
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="App user who created this test student",
    )

    # Canvas side
    canvas_user_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        comment="User ID on Canvas LMS",
    )
    canvas_domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Canvas domain this student belongs to",
    )
    display_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Name shown in Canvas",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Pseudonym unique_id on Canvas",
    )

    status: Mapped[TestStudentStatus] = mapped_column(
        SQLAlchemyEnum(
            TestStudentStatus,
            name="test_student_status",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        default=TestStudentStatus.ACTIVE,
    )

    # Optional: track current enrollment
    current_enrollment_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Most recent Canvas enrollment ID"
    )
    current_course_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Course the student is currently enrolled in"
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

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])

    __table_args__ = (
        Index("ix_test_students_owner_domain", "owner_id", "canvas_domain"),
        {"comment": "Test student accounts created on Canvas for simulations"},
    )

    def __repr__(self) -> str:
        return (
            f"<TestStudent(id={self.id}, canvas_user_id={self.canvas_user_id}, "
            f"name={self.display_name!r})>"
        )


class SimulationRun(Base):
    """
    One execution of the attempt-simulation flow.
    Records which quiz was targeted, which test student was used,
    the answers sent, and the resulting score.
    """
    __tablename__ = "simulation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Who triggered it
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Target
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    quiz_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Test student used
    test_student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("test_students.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Canvas artefacts
    canvas_submission_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="quiz_submission.id returned by Canvas"
    )
    attempt_number: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Attempt number within the quiz"
    )

    # Answers sent (list of {id, answer})
    answers_payload: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="Answers sent to Canvas"
    )

    # Result
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    kept_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    points_possible: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    status: Mapped[SimulationStatus] = mapped_column(
        SQLAlchemyEnum(
            SimulationStatus,
            name="simulation_status",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        default=SimulationStatus.PENDING,
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    test_student: Mapped[Optional["TestStudent"]] = relationship(
        "TestStudent", foreign_keys=[test_student_id]
    )

    __table_args__ = (
        Index("ix_simulation_runs_owner_quiz", "owner_id", "quiz_id"),
        {"comment": "History of quiz attempt simulations"},
    )

    def __repr__(self) -> str:
        return (
            f"<SimulationRun(id={self.id}, quiz_id={self.quiz_id}, "
            f"status={self.status})>"
        )


class CanvasAuditLog(Base):
    """
    Immutable audit trail for every Canvas mutation performed
    by the simulation system (user creation, enrollment, submission, etc.).
    """
    __tablename__ = "canvas_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Who triggered
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[AuditAction] = mapped_column(
        SQLAlchemyEnum(
            AuditAction,
            name="audit_action",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )

    # Optional reference to a simulation run
    simulation_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("simulation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Canvas artefact info
    canvas_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    canvas_course_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    canvas_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    canvas_quiz_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    canvas_submission_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Result of the action
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detail: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="JSON or free-text detail of the action result"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_audit_log_user_action", "user_id", "action"),
        Index("ix_audit_log_created", "created_at"),
        {"comment": "Immutable audit trail for Canvas mutations"},
    )

    def __repr__(self) -> str:
        return f"<CanvasAuditLog(id={self.id}, action={self.action}, success={self.success})>"
