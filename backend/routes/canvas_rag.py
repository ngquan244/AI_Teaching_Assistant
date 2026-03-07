"""
Canvas RAG API Routes
=====================
FastAPI routes for Canvas-specific Document RAG features.
Completely separate from uploaded document routes.
"""

import asyncio
import logging
import uuid as _uuid
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Form, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.auth.dependencies import CurrentUser, AdminUser
from backend.modules.document_rag.canvas_rag_service import get_canvas_rag_service
from backend.database.base import SessionLocal
from backend.services.canvas_permission import canvas_permission
from backend.services.canvas_headers import extract_canvas_headers

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Request/Response Models =====

class CanvasDownloadRequest(BaseModel):
    """Request to download a file from Canvas"""
    url: str
    filename: str
    course_id: int
    file_id: int


class CanvasIndexRequest(BaseModel):
    """Request to index a downloaded Canvas file"""
    filename: str
    course_id: Optional[int] = None  # Canvas course ID for collection naming


class CanvasExtractTopicsRequest(BaseModel):
    """Request to extract topics from a Canvas file"""
    filename: str
    num_topics: int = 8


class CanvasUpdateTopicsRequest(BaseModel):
    """Request to update topics for a Canvas file"""
    filename: str
    topics: List[str]


class CanvasQueryRequest(BaseModel):
    """Request model for Canvas RAG query"""
    question: str
    k: Optional[int] = 6
    return_context: bool = False


class CanvasGenerateQuizRequest(BaseModel):
    """Request model for quiz generation from Canvas documents"""
    topics: List[str]
    num_questions: int = 5
    difficulty: str = "medium"
    language: str = "vi"
    k: int = 10
    selected_documents: Optional[List[str]] = None


# ===== Helpers =====

def _resolve_course_id_for_filename(filename: str, user_id: str) -> Optional[int]:
    """Look up course_id for a filename from the rag_collections DB table."""
    from backend.modules.document_rag.rag_repository import SyncRAGCollectionRepository
    from backend.database.models.rag_document import RAGSourceType
    try:
        with SessionLocal() as db:
            row = SyncRAGCollectionRepository.get_by_filename(
                db, filename, _uuid.UUID(user_id),
                source=RAGSourceType.CANVAS,
            )
            if row and row.course_id:
                return row.course_id
    except Exception:
        pass
    return None


async def _check_canvas_permission(
    request: Request,
    course_id: Optional[int] = None,
    filename: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Validate Canvas token has access to the relevant course.

    Policy:
    - Headers present + Canvas API 200        → allow
    - Headers present + Canvas API 401/403    → deny (token invalid/revoked)
    - Headers present + network error         → allow (offline/degraded mode)
    - No headers + course_id known            → DENY (can't verify → refuse)
    - No headers + no course_id               → allow (nothing to check)
    """
    canvas_base_url, canvas_token = extract_canvas_headers(request)

    # Resolve course_id if not given
    cid = course_id
    if cid is None and filename and user_id:
        cid = _resolve_course_id_for_filename(filename, user_id)

    if cid is None:
        return  # No course context → nothing to check

    if not canvas_base_url or not canvas_token:
        # Course-scoped data but no Canvas credentials → deny
        raise HTTPException(
            status_code=403,
            detail="Canvas token required to access course-scoped data. "
                   "Please connect a Canvas token in Settings.",
        )

    await canvas_permission.validate_course_access(canvas_base_url, canvas_token, cid)


# ===== API Endpoints =====

@router.post("/download")
async def download_canvas_file(
    request: CanvasDownloadRequest,
    http_request: Request,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None),
    x_canvas_base_url: Optional[str] = Header(None),
):
    """
    Download a file from Canvas with MD5 deduplication.
    Requires Canvas token for authentication.
    Permission-validated: token must have access to the course.
    """
    logger.info(f"Downloading Canvas file: {request.filename}")
    
    if not x_canvas_token:
        return {
            "success": False,
            "status": "failed",
            "error": "Canvas access token not provided"
        }
    
    # Permission check
    await _check_canvas_permission(http_request, course_id=request.course_id)
    
    service = get_canvas_rag_service()
    result = await service.download_file(
        url=request.url,
        filename=request.filename,
        course_id=request.course_id,
        file_id=request.file_id,
        canvas_token=x_canvas_token,
        user_id=str(user.id)
    )
    
    return result


@router.post("/index")
async def index_canvas_file(request: CanvasIndexRequest, http_request: Request, user: CurrentUser):
    """
    Index a downloaded Canvas file.
    Stores in separate ChromaDB collection from uploaded files.
    Uses per-file collections with course_id for proper isolation.
    Permission-validated: token must have access to the course.
    """
    logger.info(f"Indexing Canvas file: {request.filename}, course_id: {request.course_id}")
    
    # Permission check (async)
    await _check_canvas_permission(
        http_request, course_id=request.course_id,
        filename=request.filename, user_id=str(user.id),
    )
    
    service = get_canvas_rag_service()
    
    # Find the file path in per-user directory
    user_dir = service._get_user_dir(str(user.id))
    file_path = user_dir / request.filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filename}")
    
    # Sync ingest → run in threadpool
    user_id = str(user.id)
    course_id = request.course_id
    def _do_ingest():
        with SessionLocal() as db:
            return service.ingest_document(
                file_path=str(file_path),
                course_id=course_id,
                user_id=user_id,
                db_session=db,
            )
    
    return await asyncio.to_thread(_do_ingest)


@router.post("/extract-topics")
async def extract_topics_for_canvas_file(
    request: CanvasExtractTopicsRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Extract topics from an indexed Canvas file.
    Permission-validated: token must have access to the course.
    """
    logger.info(f"Extracting topics for Canvas file: {request.filename}")
    
    # Permission check (async)
    await _check_canvas_permission(
        http_request, filename=request.filename, user_id=str(user.id),
    )
    
    # Sync LLM call → run in threadpool
    filename = request.filename
    num_topics = request.num_topics
    user_id = str(user.id)
    def _do_extract():
        service = get_canvas_rag_service()
        return service.extract_topics_for_file(filename, num_topics, user_id=user_id)
    
    return await asyncio.to_thread(_do_extract)


@router.get("/topics/{filename}")
async def get_canvas_document_topics(filename: str, http_request: Request, user: CurrentUser):
    """
    Get topics for a Canvas document.
    Permission-validated: token must have access to the course.
    """
    # Permission check (async)
    await _check_canvas_permission(
        http_request, filename=filename, user_id=str(user.id),
    )
    try:
        # Sync DB call → run in threadpool
        user_id = str(user.id)
        def _do_get_topics():
            service = get_canvas_rag_service()
            with SessionLocal() as db:
                return service.get_document_topics(
                    filename, user_id=user_id, db_session=db,
                )
        
        return await asyncio.to_thread(_do_get_topics)
    except Exception as e:
        logger.exception("Error getting Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.put("/topics")
async def update_canvas_document_topics(
    request: CanvasUpdateTopicsRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Update topics for a Canvas document.
    Permission-validated: token must have access to the course.
    """
    try:
        logger.info(f"Updating topics for Canvas file: {request.filename}")
        
        # Permission check (async)
        await _check_canvas_permission(
            http_request, filename=request.filename, user_id=str(user.id),
        )
        
        # Sync DB call → run in threadpool
        filename = request.filename
        topics = request.topics
        user_id = str(user.id)
        def _do_update():
            service = get_canvas_rag_service()
            with SessionLocal() as db:
                return service.update_document_topics(
                    filename, topics,
                    user_id=user_id, db_session=db,
                )
        
        return await asyncio.to_thread(_do_update)
    except Exception as e:
        logger.exception("Error updating Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/files")
def list_canvas_files(user: CurrentUser):
    """
    List all downloaded Canvas files.
    """
    service = get_canvas_rag_service()
    return service.list_downloaded_files(user_id=str(user.id))


@router.get("/indexed")
async def list_indexed_canvas_documents(
    http_request: Request,
    user: CurrentUser,
    course_id: Optional[int] = None,
):
    """
    List all indexed Canvas documents with topics.
    Optionally filter by course_id.
    Permission-validated: only returns documents for courses the token can access.
    """
    try:
        # Sync DB call → run in threadpool
        user_id = str(user.id)
        def _do_list():
            service = get_canvas_rag_service()
            with SessionLocal() as db:
                return service.list_indexed_documents(
                    user_id=user_id, db_session=db,
                )
        
        result = await asyncio.to_thread(_do_list)
        
        # Filter by course_id if provided
        if course_id is not None and result.get("success"):
            # Permission check for the specific course (async)
            await _check_canvas_permission(http_request, course_id=course_id)
            
            filtered = [
                doc for doc in result.get("documents", [])
                if doc.get("course_id") == course_id
            ]
            result["documents"] = filtered
            result["count"] = len(filtered)
        elif result.get("success"):
            # No specific course → filter to only accessible courses
            canvas_base_url, canvas_token = extract_canvas_headers(http_request)
            docs = result.get("documents", [])

            if canvas_base_url and canvas_token:
                # Token present → verify each course (async)
                course_ids = set()
                for doc in docs:
                    cid = doc.get("course_id")
                    if cid is not None:
                        course_ids.add(str(cid))
                
                if course_ids:
                    accessible = await canvas_permission.filter_accessible_courses(
                        canvas_base_url, canvas_token, list(course_ids)
                    )
                    accessible_set = set(accessible)
                    filtered = [
                        doc for doc in docs
                        if doc.get("course_id") is None
                        or str(doc.get("course_id")) in accessible_set
                    ]
                    result["documents"] = filtered
                    result["count"] = len(filtered)
            else:
                # No Canvas token → exclude ALL course-scoped docs
                filtered = [
                    doc for doc in docs
                    if doc.get("course_id") is None
                ]
                result["documents"] = filtered
                result["count"] = len(filtered)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing indexed Canvas documents")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/stats")
def get_canvas_stats(user: CurrentUser):
    """
    Get Canvas index statistics.
    """
    service = get_canvas_rag_service()
    stats = service.get_index_stats(user_id=str(user.id))
    
    return {
        "success": True,
        "stats": stats
    }


@router.post("/query")
def query_canvas_documents(request: CanvasQueryRequest, user: CurrentUser):
    """
    Query the Canvas document knowledge base.
    """
    logger.info(f"Canvas RAG Query: {request.question}")
    
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.query(
            question=request.question,
            k=request.k,
            return_context=request.return_context,
            user_id=str(user.id),
            db_session=db,
        )
    
    return result


@router.post("/generate-quiz", deprecated=True)
async def generate_quiz_from_canvas_documents(
    request: CanvasGenerateQuizRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Generate quiz from Canvas documents.

    **DEPRECATED**: Use POST /async/generate-quiz instead.
    Permission-validated when selected_documents are provided.
    """
    logger.warning("DEPRECATED sync endpoint /generate-quiz called — migrate to /async/generate-quiz")
    logger.info(f"Canvas Quiz Generation - Topics: {request.topics}")
    
    if not request.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")
    
    # Permission check: if specific documents are selected, check each (async)
    if request.selected_documents:
        for doc_name in request.selected_documents:
            await _check_canvas_permission(
                http_request, filename=doc_name, user_id=str(user.id),
            )
    
    # Sync LLM + DB call → run in threadpool
    user_id = str(user.id)
    req = request
    def _do_generate():
        service = get_canvas_rag_service()
        with SessionLocal() as db:
            return service.generate_quiz(
                topics=req.topics,
                num_questions=req.num_questions,
                difficulty=req.difficulty,
                language=req.language,
                k=req.k,
                selected_documents=req.selected_documents,
                user_id=user_id,
                db_session=db,
            )
    
    return await asyncio.to_thread(_do_generate)


@router.post("/reset")
def reset_canvas_index(admin: AdminUser):
    """
    Reset Canvas index (delete all indexed documents and files).
    """
    logger.warning("Resetting Canvas document index")
    
    service = get_canvas_rag_service()
    result = service.reset_index()
    
    return result


@router.delete("/files/{filename}")
def delete_canvas_file(filename: str, user: CurrentUser):
    """
    Delete a Canvas file's local cache and its index data.
    Does NOT delete the file from Canvas LMS.
    """
    logger.info(f"Deleting Canvas file (local): {filename}")
    
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.delete_file(filename, user_id=str(user.id), db_session=db)
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to delete file"))
    
    return result


@router.delete("/index/{filename}")
def remove_canvas_file_index(filename: str, user: CurrentUser):
    """
    Remove index for a Canvas file (keep the file).
    Cleans up: ChromaDB collection, topic data, and database records.
    Does NOT affect the file on Canvas LMS.
    """
    logger.info(f"Removing index for Canvas file: {filename}")
    
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.remove_index(filename, user_id=str(user.id), db_session=db)
    
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to remove index"))
    
    return result


# ============================================================================
# ASYNC JOB ENDPOINTS
# ============================================================================
# Return immediately with a job_id.
# The actual work runs in background via Celery.
# Poll GET /api/jobs/{job_id} for status.

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from backend.database import get_async_session
from backend.services.job_service import JobService
from backend.database.models.job import JobType
from backend import tasks
from backend.celery_app import apply_async_nonblocking


class AsyncJobResponse(BaseModel):
    """Response for async job endpoints."""
    success: bool
    job_id: str
    message: str
    status_url: str
    stream_url: str


@router.post("/async/generate-quiz", response_model=AsyncJobResponse)
async def async_canvas_generate_quiz(
    request: CanvasGenerateQuizRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate quiz from Canvas documents asynchronously (non-blocking).

    Quiz generation can take 10-60+ seconds with LLM. Returns immediately.
    Permission-validated when selected_documents are provided.
    """
    if not request.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    # Permission check for selected documents
    if request.selected_documents:
        for doc_name in request.selected_documents:
            await _check_canvas_permission(
                http_request, filename=doc_name, user_id=str(user.id),
            )

    try:
        job_service = JobService(db)

        payload = {
            "topics": request.topics,
            "num_questions": request.num_questions,
            "difficulty": request.difficulty,
            "language": request.language,
            "selected_documents": request.selected_documents,
            "user_id": str(user.id),
            "source": "canvas",
        }

        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.GENERATE_QUIZ,
            payload=payload,
        )

        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.llm_tasks.generate_quiz,
            args=[str(job.id)],
            kwargs=payload,
        )

        await job_service.set_celery_task_id(job.id, result.id)

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Canvas quiz generation queued for topics: {', '.join(request.topics)}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )

    except Exception as e:
        logger.exception("Error queueing canvas quiz generation")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/index", response_model=AsyncJobResponse)
async def async_index_canvas_file(
    request: CanvasIndexRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Index a downloaded Canvas file asynchronously (non-blocking).

    Returns a job_id immediately. Poll /api/jobs/{job_id} for status.
    Permission-validated: token must have access to the course.
    """
    # Permission check
    await _check_canvas_permission(
        http_request, course_id=request.course_id,
        filename=request.filename, user_id=str(user.id),
    )

    service = get_canvas_rag_service()
    user_dir = service._get_user_dir(str(user.id))
    file_path = user_dir / request.filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filename}")

    try:
        job_service = JobService(db)

        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.CANVAS_INDEX_FILE,
            payload={
                "filename": request.filename,
                "course_id": request.course_id,
                "file_path": str(file_path),
            },
        )

        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.rag_tasks.ingest_document,
            args=[str(job.id), str(file_path)],
            kwargs={"user_id": str(user.id)},
        )

        await job_service.set_celery_task_id(job.id, result.id)

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Indexing queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )

    except Exception as e:
        logger.exception("Error queueing canvas index job")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")
