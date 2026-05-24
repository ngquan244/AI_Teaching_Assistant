"""
RAG Tasks
=========
Celery tasks for document ingestion, indexing, and retrieval operations.
These tasks run in the 'rag' queue.
"""
import logging
import uuid
from typing import Optional, Dict, Any

from celery import shared_task

from backend.celery_app import BaseTaskWithRetry
from backend.core.config import settings
from backend.core.security import decrypt_token
from backend.database.models import AppSetting
from backend.services.job_service import get_sync_job_service
from backend.database.base import SessionLocal
from backend.modules.document_rag.document_payload import serialize_documents

logger = logging.getLogger(__name__)


def _get_rag_service():
    """Get RAG service instance (lazy import to avoid circular deps)."""
    from backend.modules.document_rag import RAGService
    return RAGService.get_instance()


def _get_canvas_rag_service():
    """Get Canvas RAG service instance."""
    from backend.modules.document_rag.canvas_rag_service import get_canvas_rag_service
    return get_canvas_rag_service()


def _resolve_groq_api_key_sync(groq_api_key: Optional[str] = None) -> Optional[str]:
    """Resolve Groq key inside the worker without storing it in job payloads."""
    if groq_api_key:
        return groq_api_key

    try:
        with SessionLocal() as db:
            record = db.get(AppSetting, "GROQ_API_KEY")
            if record and record.value:
                encrypted = record.value.get("encrypted")
                if encrypted:
                    return decrypt_token(encrypted)
    except Exception as exc:
        logger.warning("Failed to resolve Groq API key from DB in worker: %s", exc)

    env_key = settings.GROQ_API_KEY
    return env_key.strip() if env_key and env_key.strip() else None


def _build_groq_key_pool_sync(context: str):
    """Build a round-robin Groq ``KeyPool`` from the DB-backed pool table.

    Returns ``None`` when the pool is empty or cannot be loaded; the caller
    should then fall back to the single resolved key. ``context`` is only
    used for log lines so failures can be traced back to the originating task.
    """
    try:
        from backend.services.groq_key_pool_service import (
            get_pool_keys_sync,
            KeyPool,
        )
        with SessionLocal() as pool_db:
            pool_keys = get_pool_keys_sync(pool_db)
        if not pool_keys:
            return None
        pool = KeyPool(pool_keys)
        logger.info("%s: KeyPool initialized with %d keys", context, len(pool_keys))
        return pool
    except Exception as exc:
        logger.warning(
            "%s: failed to build KeyPool, falling back to single key: %s",
            context, exc,
        )
        return None


def _flush_groq_key_pool(key_pool, context: str) -> None:
    """Persist key-pool error/success counters; never raise."""
    if key_pool is None:
        return
    try:
        key_pool.flush_to_db()
    except Exception as flush_err:
        logger.warning("%s: KeyPool flush_to_db failed: %s", context, flush_err)


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.retrieve_query_context",
    queue="rag",
    max_retries=2,
)
def retrieve_query_context(
    self,
    question: str,
    k: Optional[int] = None,
    source: str = "document",
    user_id: Optional[str] = None,
    file_hashes: Optional[list] = None,
    selected_documents: Optional[list] = None,
) -> Dict[str, Any]:
    """Retrieve query documents on the rag worker and serialize them for transport."""
    with SessionLocal() as rag_db:
        if source == "canvas":
            service = _get_canvas_rag_service()
            result = service.retrieve_documents_for_query(
                question=question,
                k=k or 6,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
            )
        else:
            service = _get_rag_service()
            result = service.retrieve_documents_for_query(
                question=question,
                k=k,
                file_hashes=file_hashes,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
            )

    if result.get("success"):
        result["documents"] = serialize_documents(result.get("documents", []))
    return result


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.retrieve_quiz_context",
    queue="rag",
    max_retries=2,
)
def retrieve_quiz_context(
    self,
    topics: list,
    num_questions: int = 5,
    selected_documents: Optional[list] = None,
    user_id: Optional[str] = None,
    source: str = "document",
    include_course_domain: bool = False,
    domain_quota_ratio: Optional[float] = None,
    course_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Retrieve quiz documents on the rag worker and serialize them for transport."""
    with SessionLocal() as rag_db:
        if source == "canvas":
            if course_id is None:
                return {
                    "success": False,
                    "documents": [],
                    "error": "course_id is required for Canvas quiz generation",
                }
            service = _get_canvas_rag_service()
            result = service.retrieve_documents_for_quiz(
                topics=topics,
                num_questions=num_questions,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
                course_id=course_id,
                include_course_domain=include_course_domain,
                domain_quota_ratio=domain_quota_ratio,
            )
        else:
            service = _get_rag_service()
            result = service.retrieve_documents_for_quiz(
                topic=topics[0] if len(topics) == 1 else None,
                topics=topics,
                num_questions=num_questions,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
            )

    if result.get("success"):
        result["documents"] = serialize_documents(result.get("documents", []))
    return result


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.extract_topics_payload",
    queue="rag",
    max_retries=2,
)
def extract_topics_payload(
    self,
    source: str = "document",
    user_id: Optional[str] = None,
    groq_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Run topic extraction on the rag worker without binding to a Job row."""
    if source == "canvas":
        return {
            "success": False,
            "error": "Canvas global topic extraction is not supported by this task",
        }

    effective_groq_key = _resolve_groq_api_key_sync(groq_api_key)
    service = _get_rag_service()
    with SessionLocal() as rag_db:
        result = service.extract_topics(
            user_id=user_id,
            db_session=rag_db,
            groq_api_key=effective_groq_key,
        )
        if result.get("success"):
            rag_db.commit()
        else:
            rag_db.rollback()
        return result


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.ingest_document",
    # Indexing is memory-heavy (PDF + embeddings). Routed to the dedicated
    # ``rag_index`` queue (concurrency=1) so simultaneous index jobs do NOT
    # double-load the embedding model / chunks in RAM.
    queue="rag_index",
    max_retries=3,
    soft_time_limit=300,
    time_limit=600,
)
def ingest_document(
    self,
    job_id: str,
    file_path: str,
    skip_if_exists: bool = True,
    extract_topics: bool = True,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Ingest a PDF document into the vector store.
    
    Args:
        job_id: Job ID for tracking
        file_path: Path to PDF file
        skip_if_exists: Skip if already indexed
        extract_topics: Extract topics after indexing
        user_id: User ID for logging
        
    Returns:
        Ingestion result dict
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        # Mark job as started
        job_service.start_job(job_uuid, "Loading document")
        
        # Get RAG service
        rag_service = _get_rag_service()
        
        # Update progress
        job_service.update_progress(job_uuid, 10, "Reading PDF")
        
        # Resolve Groq key + build round-robin pool so topic extraction during
        # ingestion survives a single rate-limited / disabled key.
        groq_key = _resolve_groq_api_key_sync()
        key_pool = _build_groq_key_pool_sync("ingest_document")

        try:
            # Ingest document
            with SessionLocal() as rag_db:
                result = rag_service.ingest_document(
                    file_path=file_path,
                    skip_if_exists=skip_if_exists,
                    extract_topics=extract_topics,
                    user_id=user_id,
                    db_session=rag_db,
                    groq_api_key=groq_key,
                    key_pool=key_pool,
                )
                # Commit so the FastAPI process sees the new collection + topics
                # immediately on the next read (otherwise the writes are rolled back
                # when the session context exits, and the UI shows stale data until
                # the backend is restarted).
                if result.get("success"):
                    rag_db.commit()
                else:
                    rag_db.rollback()
        finally:
            _flush_groq_key_pool(key_pool, "ingest_document")
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Ingestion failed"))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in ingest_document task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.build_index",
    # See note on ingest_document: routed to ``rag_index`` to bound RAM.
    queue="rag_index",
    max_retries=3,
)
def build_index(
    self,
    job_id: str,
    filename: str,
    user_id: Optional[str] = None,
    course_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build/update vector index for an uploaded document.
    
    This task creates a per-file collection for the document,
    ensuring that indexing one file does NOT block other users.
    
    Args:
        job_id: Job ID for tracking
        filename: Name of uploaded file
        user_id: User ID for logging
        course_id: Optional course ID for Canvas files
    """
    from backend.core.config import settings
    from pathlib import Path
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Building per-file index for: {filename}")
        
        # Construct file path
        if user_id:
            from backend.utils import get_user_rag_dir
            rag_upload_dir = get_user_rag_dir(user_id)
        else:
            rag_upload_dir = settings.DATA_DIR / "rag_uploads"
        file_path = rag_upload_dir / filename
        
        if not file_path.exists():
            error = f"File not found: {filename}"
            job_service.fail_job(job_uuid, error)
            return {"success": False, "error": error}
        
        # Ingest document into per-file collection
        # This uses the new PerFileCollectionManager - no global locks!
        rag_service = _get_rag_service()
        groq_key = _resolve_groq_api_key_sync()
        key_pool = _build_groq_key_pool_sync("build_index")
        try:
            with SessionLocal() as rag_db:
                result = rag_service.ingest_document(
                    str(file_path), user_id=user_id, db_session=rag_db,
                    groq_api_key=groq_key, key_pool=key_pool,
                )
                if result.get("success"):
                    rag_db.commit()
                else:
                    rag_db.rollback()
        finally:
            _flush_groq_key_pool(key_pool, "build_index")
        
        if result.get("success"):
            collection_name = result.get("collection_name", "unknown")
            logger.info(f"Successfully indexed {filename} into collection: {collection_name}")
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Index build failed"))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in build_index task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.query_documents",
    queue="rag",
    max_retries=2,
    soft_time_limit=60,
    time_limit=120,
)
def query_documents(
    self,
    job_id: str,
    question: str,
    k: Optional[int] = None,
    return_context: bool = False,
    user_id: Optional[str] = None,
    file_hashes: Optional[list] = None,
    selected_documents: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Query the document knowledge base.
    
    Queries are targeted to specific per-file collections when file_hashes
    or selected_documents are provided. Otherwise queries all indexed files.
    
    Args:
        job_id: Job ID for tracking
        question: User's question
        k: Number of documents to retrieve
        return_context: Include context in response
        file_hashes: Optional list of file hashes to query
        selected_documents: Optional list of filenames to query
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Processing query")
        
        rag_service = _get_rag_service()
        with SessionLocal() as rag_db:
            result = rag_service.query(
                question=question,
                k=k,
                return_context=return_context,
                file_hashes=file_hashes,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
            )
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Query failed"))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in query_documents task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.extract_topics",
    queue="rag",
    max_retries=2,
)
def extract_topics(
    self,
    job_id: str,
    user_id: Optional[str] = None,
    groq_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract topics from indexed documents.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Extracting topics")
        
        rag_service = _get_rag_service()
        effective_groq_key = _resolve_groq_api_key_sync(groq_api_key)
        with SessionLocal() as rag_db:
            result = rag_service.extract_topics(
                user_id=user_id,
                db_session=rag_db,
                groq_api_key=effective_groq_key,
            )
            if result.get("success"):
                rag_db.commit()
            else:
                rag_db.rollback()
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in extract_topics task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.extract_topics_for_document",
    queue="rag",
    max_retries=2,
)
def extract_topics_for_document(
    self,
    job_id: str,
    filename: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-extract topics for a single uploaded document.

    Mirrors ``canvas_extract_topics`` but for the upload pipeline. Uses the
    Groq key pool so admin-rotated / disabled keys are honoured without
    a worker restart.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)

    try:
        job_service.start_job(job_uuid, f"Extracting topics for: {filename}")

        groq_key = _resolve_groq_api_key_sync()
        key_pool = _build_groq_key_pool_sync("extract_topics_for_document")

        rag_service = _get_rag_service()
        try:
            with SessionLocal() as rag_db:
                result = rag_service.extract_topics_for_document(
                    filename,
                    user_id=user_id,
                    db_session=rag_db,
                    groq_api_key=groq_key,
                    key_pool=key_pool,
                )
                if result.get("success"):
                    rag_db.commit()
                else:
                    rag_db.rollback()
        finally:
            _flush_groq_key_pool(key_pool, "extract_topics_for_document")

        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("message") or "Extract topics failed")
        return result

    except Exception as e:
        logger.exception(f"Error in extract_topics_for_document task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.canvas_index_file",
    # See note on ingest_document: routed to ``rag_index`` to bound RAM.
    queue="rag_index",
    max_retries=3,
)
def canvas_index_file(
    self,
    job_id: str,
    filename: str,
    user_id: Optional[str] = None,
    course_id: Optional[int] = None,
    file_path: Optional[str] = None,
    force_reindex: bool = False,
) -> Dict[str, Any]:
    """
    Index a downloaded Canvas file into a per-file collection.
    
    This creates a collection named like 'canvas_{course_id}_{file_hash}'
    ensuring indexing one file does NOT block other files or users.
    
    Args:
        job_id: Job ID for tracking
        filename: Name of Canvas file to index
        user_id: User ID for logging
        course_id: Canvas course ID for collection naming
        file_path: Full path to the file (supports per-user directories)
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Indexing Canvas file into per-file collection: {filename}")
        
        service = _get_canvas_rag_service()
        # Use explicit file_path when provided (per-user directory),
        # fall back to base directory for backwards compatibility.
        if file_path:
            from pathlib import Path as _Path
            file_path = _Path(file_path)
        elif user_id:
            file_path = service._get_user_dir(user_id) / filename
        else:
            file_path = service.CANVAS_RAG_DIR / filename
        
        if not file_path.exists():
            error = f"File not found: {filename}"
            job_service.fail_job(job_uuid, error)
            return {"success": False, "error": error}

        # Coarse-grained progress so the SSE stream isn't silent during the
        # slow embedding step. Stage timings come from BENCH log lines.
        job_service.update_progress(job_uuid, 15, "Loading PDF & chunking")

        # Ingest into per-file collection with course_id for naming.
        # The pool is forwarded so the inline topic-extraction step inside
        # ``ingest_document`` can rotate keys exactly like the standalone
        # ``canvas_extract_topics`` task does.
        groq_key = _resolve_groq_api_key_sync()
        key_pool = _build_groq_key_pool_sync("canvas_index_file")
        job_service.update_progress(job_uuid, 35, "Embedding chunks")
        try:
            with SessionLocal() as rag_db:
                result = service.ingest_document(
                    str(file_path), course_id=course_id,
                    user_id=user_id, db_session=rag_db,
                    groq_api_key=groq_key,
                    key_pool=key_pool,
                    force_reindex=force_reindex,
                )
        finally:
            _flush_groq_key_pool(key_pool, "canvas_index_file")
        job_service.update_progress(job_uuid, 90, "Finalizing index")
        
        if result.get("success"):
            collection_name = result.get("collection_name", "unknown")
            logger.info(f"Successfully indexed Canvas file {filename} into collection: {collection_name}")
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Index failed"))

        # Drop chunk / embedding references and force a GC pass before the
        # next task is pulled from the queue. PDF text + embedding tensors
        # can hold hundreds of MB; without this the worker process keeps
        # them alive until the generational collector decides to run.
        try:
            import gc
            return result
        finally:
            try:
                gc.collect()
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"Error in canvas_index_file task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.canvas_extract_topics",
    queue="rag",
    max_retries=2,
)
def canvas_extract_topics(
    self,
    job_id: str,
    filename: str,
    num_topics: int = 8,
    user_id: Optional[str] = None,
    course_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Extract topics from a Canvas file.

    ``course_id`` is forwarded to the service so the file lookup is scoped
    to the originating Canvas course. The same ``file_hash`` may exist in
    multiple courses; without scoping, topic extraction could resolve to
    the wrong (filename, course_id) pair.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Extracting topics from Canvas file")
        
        groq_key = _resolve_groq_api_key_sync()
        service = _get_canvas_rag_service()

        # Build round-robin Groq key pool so a single rate-limited / disabled
        # key cannot break extract topic. Errors recorded via mark_error are
        # flushed to DB at the end so the admin panel reflects health.
        key_pool = _build_groq_key_pool_sync("canvas_extract_topics")

        # IMPORTANT: use a *separate* DB session for the extraction so that
        # any rollback inside the service never affects the job-service
        # session (which tracks job lifecycle state). Sharing the session
        # caused indexed documents to "vanish" after a failed extraction
        # because the rollback would discard pending job/registry state.
        with SessionLocal() as extract_db:
            try:
                result = service.extract_topics_for_file(
                    filename, num_topics, user_id=user_id,
                    groq_api_key=groq_key,
                    db_session=extract_db,
                    key_pool=key_pool,
                    course_id=course_id,
                )
            except Exception as extract_err:
                # Topic extraction failed (e.g. Groq token exhausted on every
                # pool key). Do NOT propagate to the task — the document is
                # still indexed and we want the job to complete with empty
                # topics so the UI can show "0 chủ đề" + a regen button.
                logger.warning(
                    "Topic extraction failed for %s (filename=%s): %s",
                    job_id, filename, extract_err,
                )
                try:
                    extract_db.rollback()
                except Exception:
                    pass
                result = {
                    "success": False,
                    "topics": [],
                    "filename": filename,
                    "error": str(extract_err) or "Trích xuất chủ đề thất bại (có thể do hết hạn mức API).",
                }

        # Persist key-pool error/success counters back to DB so admin sees
        # which keys are unhealthy.
        _flush_groq_key_pool(key_pool, "canvas_extract_topics")

        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in canvas_extract_topics task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
