"""
Canvas Tasks
=============
Celery tasks for Canvas LMS API operations.
These tasks run in the 'canvas' queue with rate limiting.
"""
import logging
import uuid
import asyncio
from typing import Optional, Dict, Any, List

from celery import shared_task

from backend.celery_app import RateLimitedCanvasTask
from backend.services.canvas_connection import resolve_canvas_connection_sync
from backend.services.job_service import get_sync_job_service

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run async function in sync context."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _resolve_canvas_credentials_for_worker(
    *,
    user_id: Optional[str],
    canvas_domain: Optional[str] = None,
    legacy_canvas_token: Optional[str] = None,
    legacy_canvas_base_url: Optional[str] = None,
    require: bool = True,
    db_session=None,
) -> tuple[str, str]:
    token, base_url = resolve_canvas_connection_sync(
        user_id=user_id,
        canvas_domain_hint=canvas_domain,
        legacy_token=legacy_canvas_token,
        legacy_base_url=legacy_canvas_base_url,
        require=require,
        db=db_session,
    )
    return token, base_url


@shared_task(
    bind=True,
    base=RateLimitedCanvasTask,
    name="backend.tasks.canvas_tasks.download_file",
    queue="canvas",
    max_retries=3,
    soft_time_limit=180,
    time_limit=300,
)
def download_file(
    self,
    job_id: str,
    file_id: int,
    filename: str,
    download_url: str,
    course_id: int,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download a single file from Canvas with MD5 deduplication.
    
    Args:
        job_id: Job ID for tracking
        file_id: Canvas file ID
        filename: File name
        download_url: Signed download URL
        course_id: Canvas course ID
    """
    from backend.services.canvas_service import download_file_with_dedup
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Downloading {filename}")
        
        # Run async download function
        result = run_async(download_file_with_dedup(
            file_id=file_id,
            filename=filename,
            download_url=download_url,
            course_id=course_id,
        ))
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Download failed"))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in download_file task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedCanvasTask,
    name="backend.tasks.canvas_tasks.download_files_batch",
    queue="canvas",
    max_retries=2,
    soft_time_limit=600,
    time_limit=900,
)
def download_files_batch(
    self,
    job_id: str,
    course_id: int,
    files: List[Dict[str, Any]],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download multiple files from Canvas with MD5 deduplication.
    
    Args:
        job_id: Job ID for tracking
        course_id: Canvas course ID
        files: List of {file_id, filename, url}
    """
    from backend.services.canvas_service import download_file_with_dedup
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Downloading {len(files)} files")
        
        results = []
        saved = 0
        duplicates = 0
        failed = 0
        
        for i, file_info in enumerate(files):
            # Update progress
            progress = int((i / len(files)) * 100)
            job_service.update_progress(
                job_uuid, 
                progress, 
                f"Downloading file {i+1}/{len(files)}: {file_info.get('filename', 'unknown')}"
            )
            
            # Download file
            result = run_async(download_file_with_dedup(
                file_id=file_info["file_id"],
                filename=file_info["filename"],
                download_url=file_info["url"],
                course_id=course_id,
            ))
            results.append(result)
            
            if result.get("status") == "saved":
                saved += 1
            elif result.get("status") == "duplicate":
                duplicates += 1
            else:
                failed += 1
        
        final_result = {
            "success": failed == 0,
            "results": results,
            "total": len(files),
            "saved": saved,
            "duplicates": duplicates,
            "failed": failed,
        }
        
        if failed == 0:
            job_service.complete_job(job_uuid, final_result)
        else:
            job_service.fail_job(
                job_uuid, 
                f"Failed to download {failed} of {len(files)} files",
                result=final_result
            )
        
        return final_result
        
    except Exception as e:
        logger.exception(f"Error in download_files_batch task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedCanvasTask,
    name="backend.tasks.canvas_tasks.import_qti",
    queue="canvas",
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def import_qti(
    self,
    job_id: str,
    course_id: int,
    question_bank_name: str,
    qti_zip_base64: str,
    filename: str = "qti_import.zip",
    user_id: Optional[str] = None,
    canvas_domain: Optional[str] = None,
    canvas_token: Optional[str] = None,
    canvas_base_url: Optional[str] = None,
    token: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Import QTI package to Canvas as Question Bank.
    
    This is a multi-step operation:
    1. Create content migration
    2. Upload QTI zip to S3
    3. Finalize file attachment
    4. Poll until migration completes
    
    Args:
        job_id: Job ID for tracking
        canvas_token: Canvas API token
        canvas_base_url: Canvas instance URL
        course_id: Target course ID
        question_bank_name: Name for the question bank
        qti_zip_base64: Base64 encoded QTI zip file
        filename: Filename for the upload
    """
    import base64
    from backend.services.canvas_service import import_qti_to_canvas
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Preparing QTI import")
        
        # Decode base64
        job_service.update_progress(job_uuid, 10, "Decoding QTI package")
        try:
            qti_zip_content = base64.b64decode(qti_zip_base64)
        except Exception as e:
            job_service.fail_job(job_uuid, f"Invalid base64: {e}")
            return {"success": False, "error": f"Invalid base64: {e}"}
        
        if len(qti_zip_content) == 0:
            job_service.fail_job(job_uuid, "Empty zip file content")
            return {"success": False, "error": "Empty zip file content"}
        
        # Start import
        job_service.update_progress(job_uuid, 20, "Creating Canvas migration")
        
        effective_token, effective_base_url = _resolve_canvas_credentials_for_worker(
            user_id=user_id,
            canvas_domain=canvas_domain,
            legacy_canvas_token=canvas_token or token,
            legacy_canvas_base_url=canvas_base_url or base_url,
            db_session=db_session,
        )

        result = run_async(import_qti_to_canvas(
            token=effective_token,
            base_url=effective_base_url,
            course_id=course_id,
            question_bank_name=question_bank_name,
            qti_zip_content=qti_zip_content,
            filename=filename,
        ))
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "QTI import failed"))
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in import_qti task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedCanvasTask,
    name="backend.tasks.canvas_tasks.download_and_index",
    queue="canvas",
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def download_and_index(
    self,
    job_id: str,
    url: str,
    filename: str,
    course_id: int,
    file_id: int,
    canvas_token: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download a Canvas file and index it for RAG.
    
    This is a two-step operation:
    1. Download file with deduplication
    2. Index file for RAG queries
    """
    from backend.modules.document_rag.canvas_rag_service import get_canvas_rag_service
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Downloading {filename}")
        
        service = get_canvas_rag_service()
        effective_canvas_token = canvas_token
        if not effective_canvas_token and user_id:
            try:
                effective_canvas_token, _ = _resolve_canvas_credentials_for_worker(
                    user_id=user_id,
                    db_session=db_session,
                    require=False,
                )
            except Exception:
                effective_canvas_token = None
        
        # Step 1: Download
        job_service.update_progress(job_uuid, 20, "Downloading file")
        download_result = run_async(service.download_file(
            url=url,
            filename=filename,
            course_id=course_id,
            file_id=file_id,
            canvas_token=effective_canvas_token,
            user_id=user_id,
        ))
        
        if not download_result.get("success"):
            job_service.fail_job(job_uuid, download_result.get("error", "Download failed"))
            return download_result
        
        # Step 2: Index
        job_service.update_progress(job_uuid, 50, "Indexing document")
        user_dir = service._get_user_dir(user_id) if user_id else service.CANVAS_RAG_DIR
        file_path = user_dir / filename
        
        index_result = service.ingest_document(str(file_path), user_id=user_id)
        
        # Combine results
        final_result = {
            "success": index_result.get("success", False),
            "download": download_result,
            "index": index_result,
        }
        
        if final_result["success"]:
            job_service.complete_job(job_uuid, final_result)
        else:
            job_service.fail_job(job_uuid, index_result.get("error", "Index failed"))
        
        return final_result
        
    except Exception as e:
        logger.exception(f"Error in download_and_index task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=RateLimitedCanvasTask,
    name="backend.tasks.canvas_tasks.create_canvas_quiz",
    queue="canvas",
    max_retries=2,
    soft_time_limit=300,
    time_limit=600,
)
def create_canvas_quiz(
    self,
    job_id: str,
    course_id: int,
    quiz_params: Dict[str, Any],
    direct_questions: List[Dict[str, Any]] | None = None,
    source_questions: List[Dict[str, Any]] | None = None,
    default_points: float = 1.0,
    user_id: Optional[str] = None,
    canvas_domain: Optional[str] = None,
    canvas_token: Optional[str] = None,
    canvas_base_url: Optional[str] = None,
    token: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a full Canvas quiz (async Celery task version).
    
    Use this for large quizzes where the synchronous endpoint may time out.
    """
    from backend.services.canvas_service import build_full_quiz
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Creating quiz: {quiz_params.get('title', 'Untitled')}")
        
        job_service.update_progress(job_uuid, 10, "Building quiz on Canvas")
        
        effective_token, effective_base_url = _resolve_canvas_credentials_for_worker(
            user_id=user_id,
            canvas_domain=canvas_domain,
            legacy_canvas_token=canvas_token or token,
            legacy_canvas_base_url=canvas_base_url or base_url,
            db_session=db_session,
        )

        result = run_async(build_full_quiz(
            token=effective_token,
            base_url=effective_base_url,
            course_id=course_id,
            quiz_params=quiz_params,
            direct_questions=direct_questions,
            source_questions=source_questions,
            default_points=default_points,
        ))
        
        if result.get("success"):
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, result.get("error", "Quiz creation failed"))
        
        return result
    except Exception as e:
        logger.exception(f"Error in create_canvas_quiz task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
