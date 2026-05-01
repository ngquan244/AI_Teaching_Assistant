"""
RAG Document models for persistent collection and topic tracking.

Replaces the JSON-file-based CollectionRegistry and TopicStorage with
PostgreSQL-backed models, enabling safe concurrent access across multiple
FastAPI workers and Celery processes.
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SQLAlchemyEnum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.base import Base

if TYPE_CHECKING:
    from .user import User


class RAGSourceType(str, enum.Enum):
    """Source of the RAG document."""
    UPLOAD = "upload"
    CANVAS = "canvas"


class RAGCollection(Base):
    """
    Tracks indexed document collections in ChromaDB.

    Each row represents one user–file combination.  The actual vector data
    lives in ChromaDB; this table is the authoritative registry of *what*
    has been indexed and *for whom*.

    Replaces the former JSON-file-based ``CollectionRegistry``.
    """
    __tablename__ = "rag_collections"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique collection entry identifier",
    )

    # Owner
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="Owner user ID",
    )

    # File identity
    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MD5 hash of the source file",
    )
    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Original filename",
    )

    # ChromaDB collection name (deterministic from hash + source)
    collection_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="ChromaDB collection name",
    )

    # Source discriminator
    source: Mapped[RAGSourceType] = mapped_column(
        SQLAlchemyEnum(
            RAGSourceType,
            name="rag_source_type",
            create_constraint=True,
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        default=RAGSourceType.UPLOAD,
        comment="Document source: upload or canvas",
    )

    # Canvas-specific
    course_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Canvas course ID (NULL for regular uploads)",
    )

    # Detected language: 'vi' | 'en' | 'mixed' | NULL (unknown / pre-V1 row)
    language: Mapped[Optional[str]] = mapped_column(
        String(8),
        nullable=True,
        comment="Detected dominant language of the document",
    )

    # Index metadata
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of chunks indexed",
    )
    is_indexed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether indexing is complete",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the collection was first created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last update timestamp",
    )

    # ----- Relationships -----
    user: Mapped["User"] = relationship("User", lazy="selectin")
    topics: Mapped[Optional["RAGDocumentTopic"]] = relationship(
        "RAGDocumentTopic",
        back_populates="collection",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", "source", name="uq_rag_user_file_source"),
        Index("ix_rag_collections_user_id", "user_id"),
        Index("ix_rag_collections_user_source", "user_id", "source"),
        Index("ix_rag_collections_file_hash", "file_hash"),
        Index("ix_rag_collections_course_id", "course_id"),
        {"comment": "Registry of indexed document collections in ChromaDB"},
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary (matches legacy CollectionMetadata fields)."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "file_hash": self.file_hash,
            "filename": self.filename,
            "collection_name": self.collection_name,
            "source": self.source.value if self.source else "upload",
            "course_id": self.course_id,
            "language": self.language,
            "chunk_count": self.chunk_count,
            "is_indexed": self.is_indexed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RAGDocumentTopic(Base):
    """
    Stores extracted topics for a document collection.

    Topics are extracted once during indexing (via LLM) and cached here
    for instant retrieval.  Replaces the former ``TopicStorage`` JSON file.
    """
    __tablename__ = "rag_document_topics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Topic entry identifier",
    )

    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_collections.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="FK to rag_collections — one-to-one",
    )

    # Topics stored as JSONB array: [{"name": "...", "description": "..."}]
    topics: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment='JSON array of topic objects [{"name":"...", "description":"..."}]',
    )

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When topics were extracted",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="Last topic update",
    )

    # ----- Relationships -----
    collection: Mapped["RAGCollection"] = relationship(
        "RAGCollection",
        back_populates="topics",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_rag_topics_collection_id", "collection_id"),
        {"comment": "Cached LLM-extracted topics per document collection"},
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "collection_id": str(self.collection_id),
            "topics": self.topics or [],
            "extracted_at": self.extracted_at.isoformat() if self.extracted_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CanvasCourseDomainDoc(Base):
    """
    Marks a Canvas-indexed file as **course-level shared domain knowledge**.

    A file becomes a domain doc when a teacher (or admin) explicitly marks it
    via the API. Domain docs are visible/usable across all students enrolled
    in that Canvas course, and during quiz generation they are injected as a
    secondary supporting bucket alongside the student's own lecture selection.

    Identity is by (course_id, file_hash) so that any user's per-file Chroma
    collection (which is named deterministically from file_hash + course_id)
    can be reused without re-indexing.
    """
    __tablename__ = "canvas_course_domain_docs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Domain mark identifier",
    )

    course_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Canvas course ID this mark applies to",
    )

    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MD5 of the file (matches RAGCollection.file_hash)",
    )

    marked_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who marked this file as domain knowledge",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="False acts as a soft-delete (reversible unmark)",
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
        UniqueConstraint("course_id", "file_hash", name="uq_course_domain_doc"),
        Index("ix_course_domain_docs_course_id", "course_id"),
        Index(
            "ix_course_domain_docs_course_enabled",
            "course_id",
            "enabled",
        ),
        {"comment": "Course-level shared domain document marks (V1 RAG)"},
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "course_id": self.course_id,
            "file_hash": self.file_hash,
            "marked_by_user_id": str(self.marked_by_user_id) if self.marked_by_user_id else None,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
