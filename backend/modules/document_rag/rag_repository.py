"""
RAG Repository Layer
====================
Database-backed replacement for CollectionRegistry and TopicStorage.

Provides both async (FastAPI) and sync (Celery) interfaces for
managing RAG collection metadata and document topics.

All operations go through PostgreSQL, eliminating the cross-process
race conditions inherent in the old JSON-file-based approach.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from sqlalchemy import select, delete, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.database.models.rag_document import (
    RAGCollection,
    RAGDocumentTopic,
    RAGSourceType,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  ASYNC repository  (FastAPI routes)
# ═══════════════════════════════════════════════════════════════════════

class RAGCollectionRepository:
    """
    Async database operations for RAG collections and topics.

    Designed as a stateless helper — pass an ``AsyncSession`` to every call.
    This avoids the singleton-shared-state problem entirely: each request
    gets its own session from FastAPI's dependency injection.
    """

    # ── Collection CRUD ───────────────────────────────────────────────

    @staticmethod
    async def register(
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        file_hash: str,
        filename: str,
        collection_name: str,
        source: RAGSourceType = RAGSourceType.UPLOAD,
        course_id: Optional[int] = None,
        chunk_count: int = 0,
        is_indexed: bool = True,
    ) -> RAGCollection:
        """
        Upsert a collection entry.

        If a row with the same (user_id, file_hash, source) already exists,
        update its ``chunk_count``, ``is_indexed``, and ``updated_at``.
        Otherwise insert a new row.
        """
        stmt = (
            pg_insert(RAGCollection)
            .values(
                user_id=user_id,
                file_hash=file_hash,
                filename=filename,
                collection_name=collection_name,
                source=source,
                course_id=course_id,
                chunk_count=chunk_count,
                is_indexed=is_indexed,
            )
            .on_conflict_do_update(
                constraint="uq_rag_user_file_source",
                set_={
                    "chunk_count": chunk_count,
                    "is_indexed": is_indexed,
                    "collection_name": collection_name,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(RAGCollection)
        )
        result = await session.execute(stmt)
        row = result.scalar_one()
        await session.flush()
        return row

    @staticmethod
    async def get(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[RAGCollection]:
        """Get a single collection entry."""
        stmt = select(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        collection_id: uuid.UUID,
    ) -> Optional[RAGCollection]:
        """Get collection by primary key."""
        return await session.get(RAGCollection, collection_id)

    @staticmethod
    async def get_all(
        session: AsyncSession,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> List[RAGCollection]:
        """Get all collections for a user, optionally filtered by source."""
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)
        stmt = select(RAGCollection).where(*conditions).order_by(RAGCollection.created_at)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_filenames(
        session: AsyncSession,
        filenames: List[str],
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> List[RAGCollection]:
        """Get collections matching specific filenames."""
        conditions = [
            RAGCollection.user_id == user_id,
            RAGCollection.filename.in_(filenames),
        ]
        if source is not None:
            conditions.append(RAGCollection.source == source)
        stmt = select(RAGCollection).where(*conditions)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_course_id(
        session: AsyncSession,
        course_id: int,
        user_id: Optional[uuid.UUID] = None,
    ) -> List[RAGCollection]:
        """Get all collections for a Canvas course."""
        conditions = [RAGCollection.course_id == course_id]
        if user_id is not None:
            conditions.append(RAGCollection.user_id == user_id)
        stmt = select(RAGCollection).where(*conditions)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def is_indexed(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        """Check if a file is already indexed."""
        stmt = select(RAGCollection.is_indexed).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        return bool(row)

    @staticmethod
    async def get_collection_name(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[str]:
        """Get ChromaDB collection name for a file hash."""
        stmt = select(RAGCollection.collection_name).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def unregister(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        """Remove a collection entry. Returns True if a row was deleted."""
        stmt = delete(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0

    @staticmethod
    async def count_references(
        session: AsyncSession,
        file_hash: str,
    ) -> int:
        """Count how many users have indexed the same file (across all sources)."""
        stmt = select(func.count()).select_from(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    async def clear(
        session: AsyncSession,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> int:
        """Delete all collection entries for a user. Returns deleted count."""
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)
        stmt = delete(RAGCollection).where(*conditions)
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount

    # ── Topic CRUD ────────────────────────────────────────────────────

    @staticmethod
    async def save_topics(
        session: AsyncSession,
        *,
        collection_id: uuid.UUID,
        topics: List[Dict[str, str]],
    ) -> RAGDocumentTopic:
        """Upsert topics for a collection (one-to-one)."""
        stmt = (
            pg_insert(RAGDocumentTopic)
            .values(
                collection_id=collection_id,
                topics=topics,
            )
            .on_conflict_do_update(
                index_elements=["collection_id"],
                set_={
                    "topics": topics,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(RAGDocumentTopic)
        )
        result = await session.execute(stmt)
        row = result.scalar_one()
        await session.flush()
        return row

    @staticmethod
    async def get_topics(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[List[Dict[str, str]]]:
        """Get topics for a file by its hash."""
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.file_hash == file_hash,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_topics_by_filename(
        session: AsyncSession,
        filename: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[List[Dict[str, str]]]:
        """Get topics by document filename."""
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.filename == filename,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def has_topics(
        session: AsyncSession,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        """Check if topics exist for a document."""
        stmt = (
            select(func.count())
            .select_from(RAGDocumentTopic)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.file_hash == file_hash,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one() > 0

    @staticmethod
    async def update_topics_by_filename(
        session: AsyncSession,
        filename: str,
        topics: List[Dict[str, str]],
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        """Update topics for a document identified by filename."""
        # Find collection
        stmt = select(RAGCollection).where(
            RAGCollection.filename == filename,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = await session.execute(stmt)
        collection = result.scalar_one_or_none()
        if collection is None:
            return False

        # Upsert topics
        await RAGCollectionRepository.save_topics(
            session,
            collection_id=collection.id,
            topics=topics,
        )
        return True

    @staticmethod
    async def get_all_documents_with_topics(
        session: AsyncSession,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all indexed documents with their topic counts.
        Returns a list of dicts suitable for the frontend.
        """
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)

        stmt = (
            select(
                RAGCollection.filename,
                RAGCollection.file_hash,
                RAGCollection.chunk_count,
                RAGCollection.course_id,
                RAGCollection.created_at,
                RAGDocumentTopic.topics,
                RAGDocumentTopic.extracted_at,
            )
            .outerjoin(
                RAGDocumentTopic,
                RAGDocumentTopic.collection_id == RAGCollection.id,
            )
            .where(*conditions)
            .order_by(RAGCollection.created_at)
        )
        result = await session.execute(stmt)
        rows = result.all()

        documents = []
        for row in rows:
            topic_list = row.topics or []
            documents.append({
                "filename": row.filename,
                "file_hash": row.file_hash,
                "chunk_count": row.chunk_count,
                "course_id": row.course_id,
                "topic_count": len(topic_list),
                "extracted_at": row.extracted_at.isoformat() if row.extracted_at else None,
                "indexed_at": row.created_at.isoformat() if row.created_at else None,
            })
        return documents


# ═══════════════════════════════════════════════════════════════════════
#  SYNC repository  (Celery tasks)
# ═══════════════════════════════════════════════════════════════════════

class SyncRAGCollectionRepository:
    """
    Synchronous counterpart of RAGCollectionRepository for use in Celery
    tasks which run in sync worker threads.
    """

    @staticmethod
    def register(
        session: Session,
        *,
        user_id: uuid.UUID,
        file_hash: str,
        filename: str,
        collection_name: str,
        source: RAGSourceType = RAGSourceType.UPLOAD,
        course_id: Optional[int] = None,
        chunk_count: int = 0,
        is_indexed: bool = True,
    ) -> RAGCollection:
        stmt = (
            pg_insert(RAGCollection)
            .values(
                user_id=user_id,
                file_hash=file_hash,
                filename=filename,
                collection_name=collection_name,
                source=source,
                course_id=course_id,
                chunk_count=chunk_count,
                is_indexed=is_indexed,
            )
            .on_conflict_do_update(
                constraint="uq_rag_user_file_source",
                set_={
                    "chunk_count": chunk_count,
                    "is_indexed": is_indexed,
                    "collection_name": collection_name,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(RAGCollection)
        )
        result = session.execute(stmt)
        row = result.scalar_one()
        session.flush()
        return row

    @staticmethod
    def get(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[RAGCollection]:
        stmt = select(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def get_all(
        session: Session,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> List[RAGCollection]:
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)
        stmt = select(RAGCollection).where(*conditions).order_by(RAGCollection.created_at)
        result = session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def is_indexed(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        stmt = select(RAGCollection.is_indexed).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = session.execute(stmt)
        row = result.scalar_one_or_none()
        return bool(row)

    @staticmethod
    def get_collection_name(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[str]:
        stmt = select(RAGCollection.collection_name).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def unregister(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        stmt = delete(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = session.execute(stmt)
        session.flush()
        return result.rowcount > 0

    @staticmethod
    def count_references(
        session: Session,
        file_hash: str,
    ) -> int:
        stmt = select(func.count()).select_from(RAGCollection).where(
            RAGCollection.file_hash == file_hash,
        )
        result = session.execute(stmt)
        return result.scalar_one()

    @staticmethod
    def clear(
        session: Session,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> int:
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)
        stmt = delete(RAGCollection).where(*conditions)
        result = session.execute(stmt)
        session.flush()
        return result.rowcount

    # ── Topic CRUD ────────────────────────────────────────────────────

    @staticmethod
    def save_topics(
        session: Session,
        *,
        collection_id: uuid.UUID,
        topics: List[Dict[str, str]],
    ) -> RAGDocumentTopic:
        stmt = (
            pg_insert(RAGDocumentTopic)
            .values(
                collection_id=collection_id,
                topics=topics,
            )
            .on_conflict_do_update(
                index_elements=["collection_id"],
                set_={
                    "topics": topics,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
            .returning(RAGDocumentTopic)
        )
        result = session.execute(stmt)
        row = result.scalar_one()
        session.flush()
        return row

    @staticmethod
    def get_topics(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[List[Dict[str, str]]]:
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.file_hash == file_hash,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def get_topics_by_filename(
        session: Session,
        filename: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[List[Dict[str, str]]]:
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.filename == filename,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def has_topics(
        session: Session,
        file_hash: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(RAGDocumentTopic)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.file_hash == file_hash,
                RAGCollection.user_id == user_id,
                RAGCollection.source == source,
            )
        )
        result = session.execute(stmt)
        return result.scalar_one() > 0

    @staticmethod
    def update_topics_by_filename(
        session: Session,
        filename: str,
        topics: List[Dict[str, str]],
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> bool:
        stmt = select(RAGCollection).where(
            RAGCollection.filename == filename,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        result = session.execute(stmt)
        collection = result.scalar_one_or_none()
        if collection is None:
            return False
        SyncRAGCollectionRepository.save_topics(
            session, collection_id=collection.id, topics=topics,
        )
        return True

    @staticmethod
    def get_all_documents_with_topics(
        session: Session,
        user_id: uuid.UUID,
        source: Optional[RAGSourceType] = None,
    ) -> List[Dict[str, Any]]:
        conditions = [RAGCollection.user_id == user_id]
        if source is not None:
            conditions.append(RAGCollection.source == source)

        stmt = (
            select(
                RAGCollection.filename,
                RAGCollection.file_hash,
                RAGCollection.chunk_count,
                RAGCollection.course_id,
                RAGCollection.created_at,
                RAGDocumentTopic.topics,
                RAGDocumentTopic.extracted_at,
            )
            .outerjoin(RAGDocumentTopic, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(*conditions)
            .order_by(RAGCollection.created_at)
        )
        result = session.execute(stmt)
        rows = result.all()

        documents = []
        for row in rows:
            topic_list = row.topics or []
            documents.append({
                "filename": row.filename,
                "file_hash": row.file_hash,
                "chunk_count": row.chunk_count,
                "course_id": row.course_id,
                "topic_count": len(topic_list),
                "extracted_at": row.extracted_at.isoformat() if row.extracted_at else None,
                "indexed_at": row.created_at.isoformat() if row.created_at else None,
            })
        return documents
