"""
Job and JobEvent models for durable job tracking.
Stores job state in PostgreSQL for reliability and queryability.
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict, List, TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    Index,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


class JobType(str, enum.Enum):
    """Types of background jobs."""
    # RAG Operations
    INGEST_DOCUMENT = "INGEST_DOCUMENT"
    BUILD_INDEX = "BUILD_INDEX"
    RAG_QUERY = "RAG_QUERY"
    EXTRACT_TOPICS = "EXTRACT_TOPICS"
    
    # Quiz Operations
    GENERATE_QUIZ = "GENERATE_QUIZ"
    
    # Canvas Operations
    CANVAS_FILE_DOWNLOAD = "CANVAS_FILE_DOWNLOAD"
    CANVAS_QTI_IMPORT = "CANVAS_QTI_IMPORT"
    CANVAS_INDEX_FILE = "CANVAS_INDEX_FILE"


class JobStatus(str, enum.Enum):
    """Job execution states."""
    QUEUED = "QUEUED"        # Job created, waiting for worker
    STARTED = "STARTED"      # Worker picked up the job
    PROGRESS = "PROGRESS"    # Job is running with progress updates
    SUCCEEDED = "SUCCEEDED"  # Job completed successfully
    FAILED = "FAILED"        # Job failed (all retries exhausted)
    CANCELED = "CANCELED"    # Job was canceled by user
    REVOKED = "REVOKED"      # Job was revoked/terminated


class JobEventLevel(str, enum.Enum):
    """Log levels for job events."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Job(Base):
    """
    Durable job record for tracking background task execution.
    
    Design considerations:
    - Primary source of truth for job status (not Celery result backend)
    - Supports idempotency via unique idempotency_key
    - Stores structured payload and result as JSONB
    - Tracks progress for long-running tasks
    - Maintains audit trail via JobEvent relationship
    """
    __tablename__ = "jobs"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique job identifier"
    )
    
    # Owner (optional - some jobs may be system-initiated)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who initiated the job"
    )
    
    # Job type and status
    job_type: Mapped[JobType] = mapped_column(
        SQLAlchemyEnum(JobType, name="job_type", create_constraint=True),
        nullable=False,
        index=True,
        comment="Type of background job"
    )
    
    status: Mapped[JobStatus] = mapped_column(
        SQLAlchemyEnum(JobStatus, name="job_status", create_constraint=True),
        nullable=False,
        default=JobStatus.QUEUED,
        index=True,
        comment="Current job status"
    )
    
    # Progress tracking
    progress_pct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Progress percentage (0-100)"
    )
    
    current_step: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Description of current step"
    )
    
    # Celery task tracking
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Celery task ID for task control"
    )
    
    # Idempotency
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        comment="Unique key for idempotent job creation"
    )
    
    # Request/Response data (JSONB for efficient querying)
    payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Request parameters (sanitized, no secrets)"
    )
    
    result_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Job result data"
    )
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if job failed"
    )
    
    error_stack: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Stack trace if job failed"
    )
    
    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of retry attempts"
    )
    
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        comment="Maximum retry attempts"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="Job creation timestamp"
    )
    
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When worker started the job"
    )
    
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When job completed (success or failure)"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp"
    )
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin"
    )
    
    events: Mapped[List["JobEvent"]] = relationship(
        "JobEvent",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobEvent.created_at",
        lazy="dynamic"
    )
    
    # Indexes for common queries
    __table_args__ = (
        Index("ix_jobs_user_status", "user_id", "status"),
        Index("ix_jobs_type_status", "job_type", "status"),
        Index("ix_jobs_created_at", "created_at"),
        {"comment": "Background job tracking with durable state"}
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id) if self.user_id else None,
            "job_type": self.job_type.value,
            "status": self.status.value,
            "progress_pct": self.progress_pct,
            "current_step": self.current_step,
            "celery_task_id": self.celery_task_id,
            "payload": self.payload_json,
            "result": self.result_json,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELED,
            JobStatus.REVOKED,
        )
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.now(timezone.utc)
        return (end_time - self.started_at).total_seconds()


class JobEvent(Base):
    """
    Event log for job execution.
    Records progress updates, warnings, and errors for observability.
    """
    __tablename__ = "job_events"
    
    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique event identifier"
    )
    
    # Foreign key to job
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent job ID"
    )
    
    # Event details
    level: Mapped[JobEventLevel] = mapped_column(
        SQLAlchemyEnum(JobEventLevel, name="job_event_level", create_constraint=True),
        nullable=False,
        default=JobEventLevel.INFO,
        comment="Log level"
    )
    
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Event message"
    )
    
    # Optional structured metadata
    meta_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional event metadata"
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="Event timestamp"
    )
    
    # Relationship
    job: Mapped["Job"] = relationship(
        "Job",
        back_populates="events"
    )
    
    __table_args__ = (
        Index("ix_job_events_job_created", "job_id", "created_at"),
        {"comment": "Job execution event log"}
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "id": str(self.id),
            "job_id": str(self.job_id),
            "level": self.level.value,
            "message": self.message,
            "meta": self.meta_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
