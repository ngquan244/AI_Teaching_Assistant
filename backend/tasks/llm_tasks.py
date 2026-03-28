"""
LLM Tasks
=========
Celery tasks for LLM-intensive operations like quiz generation, chat, and topic extraction.
These tasks run in the 'llm' queue with rate limiting.
"""
import logging
import time
import uuid
from typing import Optional, Dict, Any, List

from celery import shared_task

from backend.celery_app import RateLimitedLLMTask
from backend.core.config import settings
from backend.core.security import decrypt_token
from backend.core.logger import quiz_logger, celery_logger, logger as app_logger
from backend.database.models import AppSetting
from backend.services.job_service import get_sync_job_service
from backend.database.base import SessionLocal

logger = logging.getLogger(__name__)


def _get_rag_service():
    """Get RAG service instance."""
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
    base=RateLimitedLLMTask,
    name="backend.tasks.llm_tasks.generate_quiz",
    queue="llm",
    max_retries=3,
    soft_time_limit=180,
    time_limit=300,
)
def generate_quiz(
    self,
    job_id: str,
    topics: List[str],
    num_questions: int = 5,
    difficulty: str = "medium",
    language: str = "vi",
    k: int = 10,
    selected_documents: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    source: str = "document",  # "document" or "canvas"
    groq_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate quiz questions from indexed documents.
    
    Args:
        job_id: Job ID for tracking
        topics: List of topics to generate questions about
        num_questions: Number of questions to generate
        difficulty: Difficulty level (easy/medium/hard)
        language: Language for questions (vi/en)
        k: Number of context documents to retrieve
        selected_documents: Optional filter for specific documents
        source: "document" for regular RAG, "canvas" for Canvas RAG
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    t0 = time.time()
    n_selected = len(selected_documents) if selected_documents else 0
    
    try:
        job_service.start_job(job_uuid, "Retrieving context")
        quiz_logger.info(f"Task received: job={job_id}, topics={topics}, selected_documents={selected_documents}, user_id={user_id}, source={source}")
        
        # Get appropriate RAG service
        if source == "canvas":
            rag_service = _get_canvas_rag_service()
        else:
            rag_service = _get_rag_service()
        
        # Update progress
        job_service.update_progress(job_uuid, 20, "Generating quiz questions")
        
        # Generate quiz
        effective_groq_key = _resolve_groq_api_key_sync(groq_api_key)
        with SessionLocal() as rag_db:
            result = rag_service.generate_quiz(
                topics=topics,
                num_questions=num_questions,
                difficulty=difficulty,
                language=language,
                k=k,
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=rag_db,
                groq_api_key=effective_groq_key,
            )
        
        duration = round(time.time() - t0, 1)
        n_resolved = result.get("_resolved_hashes", "?")
        
        job_service.update_progress(job_uuid, 90, "Formatting results")
        
        if result.get("success"):
            n_questions = len(result.get("questions", []))
            if result.get("partial"):
                message = result.get("message") or "Quiz generated with a small shortfall"
                app_logger.info(
                    f"[QUIZ] partial success questions={n_questions} duration={duration}s "
                    f"selected_docs={n_selected} resolved_hashes={n_resolved} message=\"{message}\""
                )
                quiz_logger.warning(f"Quiz partial success: {message}, result_keys={list(result.keys())}")
            else:
                app_logger.info(
                    f"[QUIZ] success questions={n_questions} duration={duration}s "
                    f"selected_docs={n_selected} resolved_hashes={n_resolved}"
                )
            result.pop("_resolved_hashes", None)
            job_service.complete_job(job_uuid, result)
        else:
            error_msg = result.get("error") or result.get("message") or "Quiz generation failed"
            app_logger.error(f"[QUIZ] failed duration={duration}s selected_docs={n_selected} resolved_hashes={n_resolved} error=\"{error_msg}\"")
            quiz_logger.error(f"Quiz failed: {error_msg}, result_keys={list(result.keys())}")
            result.pop("_resolved_hashes", None)
            if result.get("questions"):
                job_service.complete_job(job_uuid, result)
            else:
                job_service.fail_job(job_uuid, error_msg)
        
        return result
        
    except Exception as e:
        duration = round(time.time() - t0, 1)
        app_logger.error(f"[QUIZ] exception duration={duration}s selected_docs={n_selected} error=\"{e}\"")
        quiz_logger.exception(f"Exception in generate_quiz task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedLLMTask,
    name="backend.tasks.llm_tasks.rag_query",
    queue="llm",
    max_retries=2,
    soft_time_limit=90,
    time_limit=120,
)
def rag_query(
    self,
    job_id: str,
    question: str,
    k: Optional[int] = None,
    return_context: bool = False,
    source: str = "document",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Query documents using RAG with LLM generation.
    
    Note: This is placed in LLM queue because the LLM call is the bottleneck,
    not the vector retrieval.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Processing query")
        
        if source == "canvas":
            rag_service = _get_canvas_rag_service()
        else:
            rag_service = _get_rag_service()
        
        job_service.update_progress(job_uuid, 30, "Retrieving context")
        
        with SessionLocal() as rag_db:
            result = rag_service.query(
                question=question,
                k=k,
                return_context=return_context,
                user_id=user_id,
                db_session=rag_db,
            )
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Query failed"))
        
        return result
        
    except Exception as e:
        app_logger.exception(f"Error in rag_query task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedLLMTask,
    name="backend.tasks.llm_tasks.extract_document_topics",
    queue="llm",
    max_retries=2,
)
def extract_document_topics(
    self,
    job_id: str,
    source: str = "document",
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract topics from indexed documents using LLM.
    """
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Analyzing documents for topics")
        
        if source == "canvas":
            rag_service = _get_canvas_rag_service()
        else:
            rag_service = _get_rag_service()
        
        with SessionLocal() as rag_db:
            result = rag_service.extract_topics(user_id=user_id, db_session=rag_db)
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        app_logger.exception(f"Error in extract_document_topics task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
