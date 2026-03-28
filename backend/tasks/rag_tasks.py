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


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.rag_tasks.ingest_document",
    queue="rag",
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
        
        # Ingest document
        with SessionLocal() as rag_db:
            result = rag_service.ingest_document(
                file_path=file_path,
                skip_if_exists=skip_if_exists,
                extract_topics=extract_topics,
                user_id=user_id,
                db_session=rag_db,
            )
        
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
    queue="rag",
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
        with SessionLocal() as rag_db:
            result = rag_service.ingest_document(
                str(file_path), user_id=user_id, db_session=rag_db,
            )
        
        if result.get("success"):
            # Log the collection name for debugging
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
    name="backend.tasks.rag_tasks.canvas_index_file",
    queue="rag",
    max_retries=3,
)
def canvas_index_file(
    self,
    job_id: str,
    filename: str,
    user_id: Optional[str] = None,
    course_id: Optional[int] = None,
    file_path: Optional[str] = None,
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
        
        # Ingest into per-file collection with course_id for naming
        with SessionLocal() as rag_db:
            result = service.ingest_document(
                str(file_path), course_id=course_id,
                user_id=user_id, db_session=rag_db,
            )
        
        if result.get("success"):
            collection_name = result.get("collection_name", "unknown")
            logger.info(f"Successfully indexed Canvas file {filename} into collection: {collection_name}")
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Index failed"))
        
        return result
        
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
) -> Dict[str, Any]:
    """
    Extract topics from a Canvas file.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Extracting topics from Canvas file")
        
        service = _get_canvas_rag_service()
        result = service.extract_topics_for_file(filename, num_topics, user_id=user_id)
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in canvas_extract_topics task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
