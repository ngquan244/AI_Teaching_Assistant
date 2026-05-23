"""
SavedQuiz and SavedQuizQuestion models.

Snapshot-based quiz storage: each saved quiz is a self-contained copy of
questions at the time of saving. No live dependency on source documents,
ChromaDB collections, or job results.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User
    from .job import Job


class SavedQuiz(Base):
    """
    A user-saved quiz snapshot, organised by Canvas course.

    The quiz is fully self-contained: all question data is stored in the
    related ``SavedQuizQuestion`` rows.  ``source`` and ``source_job_id``
    are informational metadata only — deleting the source job sets the FK
    to NULL without affecting the quiz.
    """

    __tablename__ = "saved_quizzes"
    __table_args__ = (
        Index("ix_saved_quizzes_user_course", "user_id", "course_id"),
        Index("ix_saved_quizzes_user_created", "user_id", "created_at"),
        {"comment": "Snapshot-based saved quizzes organised by user and course"},
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Quiz ID",
    )

    # Owner
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Owner user ID",
    )

    # Course grouping (optional)
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Canvas course ID (NULL = unassigned)",
    )
    course_name: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Course name snapshot for display",
    )

    # Quiz metadata
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Quiz title",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Quiz description",
    )
    difficulty: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Difficulty level: easy / medium / hard",
    )
    language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Language code: vi / en",
    )

    # Source provenance (informational only)
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="manual",
        comment="Origin: rag_generation | canvas_import | manual",
    )
    source_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        comment="Originating job ID (informational, SET NULL on delete)",
    )

    # Flexible tagging
    tags: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        server_default="[]",
        comment="Free-form tags array",
    )

    # Denormalised count for fast listing
    question_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Number of questions (denormalised)",
    )

    # User-facing flags
    is_starred: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="Starred / pinned by user",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Creation timestamp",
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp",
    )

    # Relationships
    questions: Mapped[List["SavedQuizQuestion"]] = relationship(
        "SavedQuizQuestion",
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="SavedQuizQuestion.question_number",
        lazy="selectin",
    )
    owner: Mapped["User"] = relationship("User", lazy="noload")
    source_job: Mapped[Optional["Job"]] = relationship("Job", lazy="noload")

    def __repr__(self) -> str:
        return f"<SavedQuiz {self.id} title={self.title!r} user={self.user_id}>"


class SavedQuizQuestion(Base):
    """
    A single question within a saved quiz snapshot.

    All content fields are copied at save-time and are independent of
    the original source material.
    """

    __tablename__ = "saved_quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "question_number", name="uq_saved_quiz_question_num"),
        {"comment": "Individual questions belonging to a saved quiz snapshot"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Question ID",
    )
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("saved_quizzes.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent quiz ID",
    )
    question_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="1-based display order",
    )
    question_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Question body (snapshot)",
    )
    options: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='Answer options: {"A": "...", "B": "...", "C": "...", "D": "..."}',
    )
    correct_answer: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        comment="Correct option key (A/B/C/D)",
    )
    explanation: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Answer explanation (snapshot)",
    )
    question_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="multiple_choice",
        comment="Question type for future extensibility",
    )
    points: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default="1.0",
        comment="Points awarded for correct answer",
    )

    # Relationship back to parent quiz
    quiz: Mapped["SavedQuiz"] = relationship(
        "SavedQuiz",
        back_populates="questions",
    )

    def __repr__(self) -> str:
        return f"<SavedQuizQuestion {self.id} quiz={self.quiz_id} #{self.question_number}>"
