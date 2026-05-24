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
    CanvasCourseDomainDoc,
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
        Upsert an *upload* collection entry.

        Conflicts are resolved against the partial unique index
        ``uq_rag_user_file_upload`` (user_id, file_hash) WHERE source='upload'.
        Canvas rows MUST go through :meth:`register_canvas` because their
        identity also includes ``course_id`` — registering a Canvas file
        through this method would silently collide across courses.
        """
        if source != RAGSourceType.UPLOAD:
            raise ValueError(
                "RAGCollectionRepository.register() only supports UPLOAD source; "
                "use register_canvas() for Canvas files."
            )
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
                index_elements=["user_id", "file_hash"],
                index_where=RAGCollection.source == RAGSourceType.UPLOAD.value,
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
        """Get topics by document filename.

        NOTE: Not safe for Canvas — the same filename may exist in multiple
        courses for the same user. Use :meth:`get_topics_by_filename_canvas`
        for Canvas lookups.
        """
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
    async def get_topics_by_filename_canvas(
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        course_id: int,
        filename: str,
    ) -> Optional[List[Dict[str, str]]]:
        """Get topics for a Canvas document scoped to a specific course.

        Filters on (user_id, course_id, filename, source=CANVAS). Returns
        ``None`` if no matching row has topics. Uses ``.first()`` rather than
        ``scalar_one_or_none`` so collisions (e.g. same filename, different
        hashes within the same course) never raise MultipleResultsFound;
        the most recently updated row wins.
        """
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.filename == filename,
                RAGCollection.user_id == user_id,
                RAGCollection.course_id == course_id,
                RAGCollection.source == RAGSourceType.CANVAS,
            )
            .order_by(RAGDocumentTopic.updated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        row = result.first()
        return row[0] if row else None

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
        language: Optional[str] = None,
    ) -> RAGCollection:
        if source != RAGSourceType.UPLOAD:
            raise ValueError(
                "SyncRAGCollectionRepository.register() only supports UPLOAD source; "
                "use register_canvas() for Canvas files."
            )
        values: Dict[str, Any] = dict(
            user_id=user_id,
            file_hash=file_hash,
            filename=filename,
            collection_name=collection_name,
            source=source,
            course_id=course_id,
            chunk_count=chunk_count,
            is_indexed=is_indexed,
        )
        update_set: Dict[str, Any] = {
            "chunk_count": chunk_count,
            "is_indexed": is_indexed,
            "collection_name": collection_name,
            "updated_at": datetime.now(timezone.utc),
        }
        if language is not None:
            values["language"] = language
            update_set["language"] = language
        stmt = (
            pg_insert(RAGCollection)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id", "file_hash"],
                index_where=RAGCollection.source == RAGSourceType.UPLOAD.value,
                set_=update_set,
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
    def get_by_filename(
        session: Session,
        filename: str,
        user_id: uuid.UUID,
        source: RAGSourceType = RAGSourceType.UPLOAD,
    ) -> Optional[RAGCollection]:
        """Look up a collection by filename + user + source.

        Falls back to a case/whitespace/comma-insensitive match so the
        frontend can pass either the canonical filename or a sanitized
        display name (the two diverge for Canvas files with commas / odd
        spacing).
        """
        stmt = select(RAGCollection).where(
            RAGCollection.filename == filename,
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is not None:
            return row

        def _norm(name: str) -> str:
            return " ".join(name.lower().replace(",", "").split())

        target = _norm(filename)
        target_base = target[:-4] if target.endswith(".pdf") else target

        all_stmt = select(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.source == source,
        )
        for candidate in session.execute(all_stmt).scalars():
            cand = _norm(candidate.filename or "")
            cand_base = cand[:-4] if cand.endswith(".pdf") else cand
            if cand == target or cand_base == target_base:
                return candidate
            if target_base and (target_base in cand_base or cand_base in target_base):
                return candidate
        return None

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
    def get_by_filenames(
        session: Session,
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

    # ── Language helpers (V1 course domain knowledge) ────────────────

    @staticmethod
    def get_language_by_hash(
        session: Session,
        file_hash: str,
    ) -> Optional[str]:
        """Best-effort language lookup keyed only by file_hash.

        Cross-user: any indexed copy of the same file should agree on
        language. Returns the first non-NULL language found.
        """
        stmt = (
            select(RAGCollection.language)
            .where(
                RAGCollection.file_hash == file_hash,
                RAGCollection.language.is_not(None),
            )
            .limit(1)
        )
        result = session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def get_language_by_hashes(
        session: Session,
        hashes: List[str],
    ) -> Dict[str, str]:
        """Bulk language lookup; returns only entries that have a value."""
        if not hashes:
            return {}
        stmt = (
            select(RAGCollection.file_hash, RAGCollection.language)
            .where(
                RAGCollection.file_hash.in_(hashes),
                RAGCollection.language.is_not(None),
            )
        )
        result = session.execute(stmt)
        out: Dict[str, str] = {}
        for fh, lang in result.all():
            if fh and lang and fh not in out:
                out[fh] = lang
        return out

    @staticmethod
    def get_by_hashes(
        session: Session,
        hashes: List[str],
        source: Optional[RAGSourceType] = None,
        course_id: Optional[int] = None,
    ) -> List[RAGCollection]:
        """Return all RAGCollection rows matching any of ``hashes``.

        Optional filters narrow the result by ``source`` (e.g. CANVAS only)
        and/or by ``course_id``. Used by V2 eligibility validation:
        domain-doc mark requests must verify that every requested hash
        corresponds to a Canvas-indexed file in the target course.
        """
        if not hashes:
            return []
        stmt = select(RAGCollection).where(RAGCollection.file_hash.in_(hashes))
        if source is not None:
            stmt = stmt.where(RAGCollection.source == source)
        if course_id is not None:
            stmt = stmt.where(RAGCollection.course_id == course_id)
        return list(session.execute(stmt).scalars().all())

    # ── Canvas-only helpers (per-course identity) ─────────────────────
    #
    # All lookups / writes for ``source=CANVAS`` MUST go through these
    # helpers so they include ``course_id`` in the scoping clause. The
    # legacy ``register / get / is_indexed / get_collection_name /
    # unregister / has_topics / get_topics`` methods above match by
    # ``(user_id, file_hash)`` only, which causes cross-course collision
    # when the same file content is indexed in two different courses.
    # See alembic migration 016_canvas_unique_per_course.

    @staticmethod
    def get_canvas_by_course_and_hash(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> Optional[RAGCollection]:
        stmt = select(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.course_id == course_id,
            RAGCollection.file_hash == file_hash,
            RAGCollection.source == RAGSourceType.CANVAS,
        )
        return session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def is_indexed_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> bool:
        row = SyncRAGCollectionRepository.get_canvas_by_course_and_hash(
            session, user_id=user_id, course_id=course_id, file_hash=file_hash,
        )
        return bool(row and row.is_indexed)

    @staticmethod
    def get_collection_name_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> Optional[str]:
        row = SyncRAGCollectionRepository.get_canvas_by_course_and_hash(
            session, user_id=user_id, course_id=course_id, file_hash=file_hash,
        )
        return row.collection_name if row else None

    @staticmethod
    def get_by_filename_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        filename: str,
    ) -> Optional[RAGCollection]:
        """Same fuzzy-match logic as :meth:`get_by_filename` but scoped
        to (user_id, course_id, source=CANVAS)."""
        stmt = select(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.course_id == course_id,
            RAGCollection.source == RAGSourceType.CANVAS,
            RAGCollection.filename == filename,
        )
        row = session.execute(stmt).scalar_one_or_none()
        if row is not None:
            return row

        def _norm(name: str) -> str:
            return " ".join(name.lower().replace(",", "").split())

        target = _norm(filename)
        target_base = target[:-4] if target.endswith(".pdf") else target

        all_stmt = select(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.course_id == course_id,
            RAGCollection.source == RAGSourceType.CANVAS,
        )
        for candidate in session.execute(all_stmt).scalars():
            cand = _norm(candidate.filename or "")
            cand_base = cand[:-4] if cand.endswith(".pdf") else cand
            if cand == target or cand_base == target_base:
                return candidate
            if target_base and (target_base in cand_base or cand_base in target_base):
                return candidate
        return None

    @staticmethod
    def get_by_filenames_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        filenames: List[str],
    ) -> List[RAGCollection]:
        """Get Canvas collections matching a set of filenames, scoped to one course.

        Use this instead of :meth:`get_by_filenames` for Canvas retrieval: the
        same filename / file_hash can exist under multiple Canvas courses for
        the same user, and a course-agnostic lookup will return ambiguous
        cross-course rows that poison ``hash_to_collection_name`` and end up
        querying the wrong (or a non-existent) Chroma collection.
        """
        if not filenames:
            return []
        stmt = select(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.course_id == course_id,
            RAGCollection.source == RAGSourceType.CANVAS,
            RAGCollection.filename.in_(filenames),
        )
        return list(session.execute(stmt).scalars().all())

    @staticmethod
    def unregister_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> bool:
        stmt = delete(RAGCollection).where(
            RAGCollection.user_id == user_id,
            RAGCollection.course_id == course_id,
            RAGCollection.file_hash == file_hash,
            RAGCollection.source == RAGSourceType.CANVAS,
        )
        result = session.execute(stmt)
        session.flush()
        return result.rowcount > 0

    @staticmethod
    def register_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
        filename: str,
        collection_name: str,
        chunk_count: int = 0,
        is_indexed: bool = True,
        language: Optional[str] = None,
    ) -> RAGCollection:
        """Upsert a Canvas RAGCollection row scoped to
        ``(user_id, course_id, file_hash)``.

        Uses ON CONFLICT against the partial unique index
        ``uq_rag_user_file_canvas_course`` so concurrent writers race
        atomically at the DB level instead of two transactions both
        passing a SELECT and one losing on INSERT. ``course_id`` is
        required (not nullable) because the legacy partial index
        ``uq_rag_user_file_canvas_legacy`` is only a safety net for
        pre-V1 rows; all new Canvas writes go through this path.
        """
        if course_id is None:
            raise ValueError("register_canvas requires course_id (got None)")

        values: Dict[str, Any] = dict(
            user_id=user_id,
            file_hash=file_hash,
            filename=filename,
            collection_name=collection_name,
            source=RAGSourceType.CANVAS,
            course_id=course_id,
            chunk_count=chunk_count,
            is_indexed=is_indexed,
        )
        update_set: Dict[str, Any] = {
            "filename": filename,
            "collection_name": collection_name,
            "chunk_count": chunk_count,
            "is_indexed": is_indexed,
            "updated_at": datetime.now(timezone.utc),
        }
        if language is not None:
            values["language"] = language
            update_set["language"] = language

        stmt = (
            pg_insert(RAGCollection)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id", "file_hash", "course_id"],
                index_where=and_(
                    RAGCollection.source == RAGSourceType.CANVAS.value,
                    RAGCollection.course_id.is_not(None),
                ),
                set_=update_set,
            )
            .returning(RAGCollection)
        )
        row = session.execute(stmt).scalar_one()
        session.flush()
        return row

    @staticmethod
    def has_topics_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(RAGDocumentTopic)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.user_id == user_id,
                RAGCollection.course_id == course_id,
                RAGCollection.file_hash == file_hash,
                RAGCollection.source == RAGSourceType.CANVAS,
            )
        )
        return session.execute(stmt).scalar_one() > 0

    @staticmethod
    def get_topics_canvas(
        session: Session,
        *,
        user_id: uuid.UUID,
        course_id: int,
        file_hash: str,
    ) -> Optional[List[Dict[str, str]]]:
        stmt = (
            select(RAGDocumentTopic.topics)
            .join(RAGCollection, RAGDocumentTopic.collection_id == RAGCollection.id)
            .where(
                RAGCollection.user_id == user_id,
                RAGCollection.course_id == course_id,
                RAGCollection.file_hash == file_hash,
                RAGCollection.source == RAGSourceType.CANVAS,
            )
        )
        return session.execute(stmt).scalar_one_or_none()


# ═══════════════════════════════════════════════════════════════════════
#  Course-level domain document marks (V1)
# ═══════════════════════════════════════════════════════════════════════

class SyncCanvasCourseDomainDocRepository:
    """
    Sync repository for ``canvas_course_domain_docs``.

    Marks a Canvas-indexed file as **course-level shared domain knowledge**.
    Identity is by ``(course_id, file_hash)`` so any user's per-file Chroma
    collection (deterministic name) can be reused without re-indexing.
    """

    @staticmethod
    def get_enabled(
        session: Session,
        course_id: int,
    ) -> List[CanvasCourseDomainDoc]:
        """Return enabled domain marks for a course."""
        stmt = (
            select(CanvasCourseDomainDoc)
            .where(
                CanvasCourseDomainDoc.course_id == course_id,
                CanvasCourseDomainDoc.enabled.is_(True),
            )
        )
        result = session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def get_enabled_hashes(
        session: Session,
        course_id: int,
    ) -> List[str]:
        """Return file_hash values of enabled domain marks for a course."""
        stmt = (
            select(CanvasCourseDomainDoc.file_hash)
            .where(
                CanvasCourseDomainDoc.course_id == course_id,
                CanvasCourseDomainDoc.enabled.is_(True),
            )
        )
        result = session.execute(stmt)
        return [row for row in result.scalars().all()]

    @staticmethod
    def is_marked(
        session: Session,
        course_id: int,
        file_hash: str,
    ) -> bool:
        stmt = (
            select(func.count())
            .select_from(CanvasCourseDomainDoc)
            .where(
                CanvasCourseDomainDoc.course_id == course_id,
                CanvasCourseDomainDoc.file_hash == file_hash,
                CanvasCourseDomainDoc.enabled.is_(True),
            )
        )
        result = session.execute(stmt)
        return (result.scalar_one() or 0) > 0

    @staticmethod
    def get_marked_subset(
        session: Session,
        course_id: int,
        hashes: List[str],
    ) -> set:
        """Return the subset of given hashes that are enabled domain marks."""
        if not hashes:
            return set()
        stmt = (
            select(CanvasCourseDomainDoc.file_hash)
            .where(
                CanvasCourseDomainDoc.course_id == course_id,
                CanvasCourseDomainDoc.file_hash.in_(hashes),
                CanvasCourseDomainDoc.enabled.is_(True),
            )
        )
        result = session.execute(stmt)
        return {row for row in result.scalars().all()}

    @staticmethod
    def upsert_many(
        session: Session,
        *,
        course_id: int,
        file_hashes: List[str],
        marked_by_user_id: Optional[uuid.UUID] = None,
    ) -> int:
        """Idempotent mark — re-enables previously disabled rows.

        Returns the number of input hashes processed (not new rows).
        """
        if not file_hashes:
            return 0
        now = datetime.now(timezone.utc)
        for fh in file_hashes:
            stmt = (
                pg_insert(CanvasCourseDomainDoc)
                .values(
                    course_id=course_id,
                    file_hash=fh,
                    marked_by_user_id=marked_by_user_id,
                    enabled=True,
                )
                .on_conflict_do_update(
                    constraint="uq_course_domain_doc",
                    set_={
                        "enabled": True,
                        "marked_by_user_id": marked_by_user_id,
                        "updated_at": now,
                    },
                )
            )
            session.execute(stmt)
        session.flush()
        return len(file_hashes)

    @staticmethod
    def disable(
        session: Session,
        *,
        course_id: int,
        file_hash: str,
    ) -> bool:
        """Soft-delete (reversible). Returns True if a row was updated."""
        stmt = (
            update(CanvasCourseDomainDoc)
            .where(
                CanvasCourseDomainDoc.course_id == course_id,
                CanvasCourseDomainDoc.file_hash == file_hash,
            )
            .values(enabled=False, updated_at=datetime.now(timezone.utc))
        )
        result = session.execute(stmt)
        session.flush()
        return result.rowcount > 0

    @staticmethod
    def list_for_course(
        session: Session,
        course_id: int,
        include_disabled: bool = False,
    ) -> List[CanvasCourseDomainDoc]:
        conditions = [CanvasCourseDomainDoc.course_id == course_id]
        if not include_disabled:
            conditions.append(CanvasCourseDomainDoc.enabled.is_(True))
        stmt = select(CanvasCourseDomainDoc).where(*conditions)
        result = session.execute(stmt)
        return list(result.scalars().all())
