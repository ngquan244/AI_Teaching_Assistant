"""
Canvas RAG API Routes
=====================
FastAPI routes for Canvas-specific Document RAG features.
Completely separate from uploaded document routes.
"""

import asyncio
import logging
import uuid as _uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend import tasks
from backend.auth.dependencies import AdminUser, CurrentUser
from backend.celery_app import apply_async_nonblocking
from backend.database import get_async_session
from backend.database.base import SessionLocal
from backend.database.models.job import JobType
from backend.database.models.rag_document import RAGSourceType
from backend.modules.document_rag.canvas_rag_service import get_canvas_rag_service
from backend.modules.document_rag.rag_repository import SyncRAGCollectionRepository
from backend.services.canvas_connection import resolve_canvas_connection_async
from backend.services.canvas_permission import canvas_permission
from backend.services.canvas_service import fetch_canvas_courses
from backend.services.job_service import JobService
from backend.services.url_safety import validate_download_url

logger = logging.getLogger(__name__)
router = APIRouter()


class CanvasDownloadRequest(BaseModel):
    """Request to download a file from Canvas."""
    url: str
    filename: str
    course_id: int
    file_id: int


class CanvasIndexRequest(BaseModel):
    """Request to index a downloaded Canvas file."""
    filename: str
    course_id: Optional[int] = None


class CanvasExtractTopicsRequest(BaseModel):
    """Request to extract topics from a Canvas file."""
    filename: str
    num_topics: int = 8


class CanvasUpdateTopicsRequest(BaseModel):
    """Request to update topics for a Canvas file."""
    filename: str
    topics: List[str]


class CanvasQueryRequest(BaseModel):
    """Request model for Canvas RAG query."""
    question: str
    k: Optional[int] = 6
    return_context: bool = False
    selected_documents: Optional[List[str]] = None


class CanvasGenerateQuizRequest(BaseModel):
    """Request model for quiz generation from Canvas documents."""
    topics: List[str]
    num_questions: int = 5
    difficulty: str = "medium"
    language: str = "vi"
    k: int = 10
    selected_documents: Optional[List[str]] = None


class AsyncJobResponse(BaseModel):
    """Response for async job endpoints."""
    success: bool
    job_id: str
    message: str
    status_url: str
    stream_url: str


def _resolve_course_id_for_filename(filename: str, user_id: str) -> Optional[int]:
    """Look up course_id for a filename from the rag_collections table."""
    try:
        with SessionLocal() as db:
            row = SyncRAGCollectionRepository.get_by_filename(
                db,
                filename,
                _uuid.UUID(user_id),
                source=RAGSourceType.CANVAS,
            )
            if row and row.course_id:
                return row.course_id
    except Exception:
        pass
    return None


def _list_canvas_documents_for_user(user_id: str) -> List[dict]:
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.list_indexed_documents(
            user_id=user_id,
            db_session=db,
        )
    return result.get("documents", []) if result.get("success") else []


async def _get_accessible_canvas_documents(
    request: Request,
    user_id: str,
    selected_documents: Optional[List[str]] = None,
) -> tuple[List[dict], Optional[str], Optional[str]]:
    docs = _list_canvas_documents_for_user(user_id)
    if selected_documents is not None:
        selected_set = set(selected_documents)
        docs = [doc for doc in docs if doc.get("filename") in selected_set]

    canvas_token, canvas_base_url = await resolve_canvas_connection_async(
        user_id=user_id,
        request=request,
        require=False,
    )

    if not docs:
        return [], canvas_token, canvas_base_url

    course_ids = {
        str(doc.get("course_id"))
        for doc in docs
        if doc.get("course_id") is not None
    }
    if not course_ids:
        return docs, canvas_token, canvas_base_url

    if not canvas_token or not canvas_base_url:
        filtered = [doc for doc in docs if doc.get("course_id") is None]
        return filtered, canvas_token, canvas_base_url

    accessible = await canvas_permission.filter_accessible_courses(
        canvas_base_url,
        canvas_token,
        list(course_ids),
    )
    accessible_set = set(accessible)
    filtered = [
        doc for doc in docs
        if doc.get("course_id") is None
        or str(doc.get("course_id")) in accessible_set
    ]
    return filtered, canvas_token, canvas_base_url


async def _check_canvas_permission(
    request: Request,
    course_id: Optional[int] = None,
    filename: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Validate the active Canvas connection can access the relevant course."""
    cid = course_id
    if cid is None and filename and user_id:
        cid = _resolve_course_id_for_filename(filename, user_id)

    if cid is None:
        return

    canvas_token, canvas_base_url = await resolve_canvas_connection_async(
        user_id=user_id,
        request=request,
        require=False,
    )
    if not canvas_token or not canvas_base_url:
        raise HTTPException(
            status_code=403,
            detail="Canvas token required to access course-scoped data. Please connect a Canvas token in Settings.",
        )

    await canvas_permission.validate_course_access(canvas_base_url, canvas_token, cid)


async def _require_accessible_document_names(
    request: Request,
    user_id: str,
    selected_documents: Optional[List[str]] = None,
) -> List[str]:
    docs, _, _ = await _get_accessible_canvas_documents(
        request,
        user_id,
        selected_documents=selected_documents,
    )
    document_names = [doc["filename"] for doc in docs if doc.get("filename")]
    if not document_names:
        raise HTTPException(
            status_code=403,
            detail="Current Canvas token does not have access to any indexed Canvas documents for this request.",
        )
    return document_names


@router.post("/download")
async def download_canvas_file(
    request: CanvasDownloadRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Download a file from Canvas with MD5 deduplication.
    Permission-validated: active token must have access to the course.
    """
    logger.info("Downloading Canvas file: %s", request.filename)

    await _check_canvas_permission(
        http_request,
        course_id=request.course_id,
        user_id=str(user.id),
    )
    canvas_token, _ = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )

    service = get_canvas_rag_service()
    result = await service.download_file(
        url=validate_download_url(request.url),
        filename=request.filename,
        course_id=request.course_id,
        file_id=request.file_id,
        canvas_token=canvas_token,
        user_id=str(user.id),
    )
    return result


@router.post("/index")
async def index_canvas_file(
    request: CanvasIndexRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Index a downloaded Canvas file.
    Stores in separate ChromaDB collections from uploaded files.
    """
    logger.info("Indexing Canvas file: %s, course_id: %s", request.filename, request.course_id)

    await _check_canvas_permission(
        http_request,
        course_id=request.course_id,
        filename=request.filename,
        user_id=str(user.id),
    )

    service = get_canvas_rag_service()
    user_dir = service._get_user_dir(str(user.id))
    file_path = user_dir / request.filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filename}")

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
    """Extract topics from an indexed Canvas file."""
    logger.info("Extracting topics for Canvas file: %s", request.filename)
    await _check_canvas_permission(
        http_request,
        filename=request.filename,
        user_id=str(user.id),
    )

    filename = request.filename
    num_topics = request.num_topics
    user_id = str(user.id)

    def _do_extract():
        service = get_canvas_rag_service()
        return service.extract_topics_for_file(filename, num_topics, user_id=user_id)

    return await asyncio.to_thread(_do_extract)


@router.get("/topics/{filename}")
async def get_canvas_document_topics(
    filename: str,
    http_request: Request,
    user: CurrentUser,
):
    """Get topics for a Canvas document."""
    await _check_canvas_permission(
        http_request,
        filename=filename,
        user_id=str(user.id),
    )
    try:
        user_id = str(user.id)

        def _do_get_topics():
            service = get_canvas_rag_service()
            with SessionLocal() as db:
                return service.get_document_topics(
                    filename,
                    user_id=user_id,
                    db_session=db,
                )

        return await asyncio.to_thread(_do_get_topics)
    except Exception:
        logger.exception("Error getting Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.put("/topics")
async def update_canvas_document_topics(
    request: CanvasUpdateTopicsRequest,
    http_request: Request,
    user: CurrentUser,
):
    """Update topics for a Canvas document."""
    try:
        logger.info("Updating topics for Canvas file: %s", request.filename)
        await _check_canvas_permission(
            http_request,
            filename=request.filename,
            user_id=str(user.id),
        )

        filename = request.filename
        topics = request.topics
        user_id = str(user.id)

        def _do_update():
            service = get_canvas_rag_service()
            with SessionLocal() as db:
                return service.update_document_topics(
                    filename,
                    topics,
                    user_id=user_id,
                    db_session=db,
                )

        return await asyncio.to_thread(_do_update)
    except Exception:
        logger.exception("Error updating Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/files")
def list_canvas_files(user: CurrentUser):
    """List all downloaded Canvas files."""
    service = get_canvas_rag_service()
    return service.list_downloaded_files(user_id=str(user.id))


@router.get("/indexed")
async def list_indexed_canvas_documents(
    http_request: Request,
    user: CurrentUser,
    course_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """
    List indexed Canvas documents, filtering out inaccessible course-scoped docs.
    """
    try:
        user_id = str(user.id)
        docs, canvas_token, canvas_base_url = await _get_accessible_canvas_documents(
            http_request,
            user_id,
        )

        if course_id is not None:
            await _check_canvas_permission(http_request, course_id=course_id, user_id=user_id)
            docs = [doc for doc in docs if doc.get("course_id") == course_id]

        total = len(docs)
        offset = (page - 1) * page_size
        paged_docs = docs[offset:offset + page_size]

        if canvas_token and canvas_base_url:
            cids = {doc.get("course_id") for doc in paged_docs if doc.get("course_id") is not None}
            if cids:
                try:
                    courses_resp = await fetch_canvas_courses(canvas_token, canvas_base_url)
                    if courses_resp.get("success"):
                        name_map = {
                            course["id"]: course["name"]
                            for course in courses_resp.get("courses", [])
                            if "id" in course and "name" in course
                        }
                        for doc in paged_docs:
                            cid = doc.get("course_id")
                            if cid is not None and cid in name_map:
                                doc["course_name"] = name_map[cid]
                except Exception:
                    pass

        return {
            "success": True,
            "documents": paged_docs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 1,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error listing indexed Canvas documents")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/stats")
def get_canvas_stats(user: CurrentUser):
    """Get Canvas index statistics."""
    service = get_canvas_rag_service()
    stats = service.get_index_stats(user_id=str(user.id))
    return {"success": True, "stats": stats}


@router.post("/query")
async def query_canvas_documents(
    request: CanvasQueryRequest,
    http_request: Request,
    user: CurrentUser,
):
    """Query the Canvas document knowledge base."""
    logger.info("Canvas RAG Query: %s", request.question)

    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    selected_documents = await _require_accessible_document_names(
        http_request,
        str(user.id),
        selected_documents=request.selected_documents,
    )

    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.query(
            question=request.question,
            k=request.k,
            return_context=request.return_context,
            selected_documents=selected_documents,
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

    If no documents are explicitly selected, the request is scoped to all
    currently accessible indexed Canvas documents.
    """
    logger.warning("DEPRECATED sync endpoint /generate-quiz called - migrate to /async/generate-quiz")
    logger.info("Canvas Quiz Generation - Topics: %s", request.topics)

    if not request.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    selected_documents = await _require_accessible_document_names(
        http_request,
        str(user.id),
        selected_documents=request.selected_documents,
    )

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
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=db,
            )

    return await asyncio.to_thread(_do_generate)


@router.post("/reset")
def reset_canvas_index(admin: AdminUser):
    """Reset Canvas index (delete all indexed documents and files)."""
    logger.warning("Resetting Canvas document index")
    service = get_canvas_rag_service()
    return service.reset_index()


@router.delete("/files/{filename}")
def delete_canvas_file(filename: str, user: CurrentUser):
    """Delete a Canvas file's local cache and its index data."""
    logger.info("Deleting Canvas file (local): %s", filename)
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.delete_file(filename, user_id=str(user.id), db_session=db)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to delete file"))
    return result


@router.delete("/index/{filename}")
def remove_canvas_file_index(filename: str, user: CurrentUser):
    """Remove index for a Canvas file (keep the local file)."""
    logger.info("Removing index for Canvas file: %s", filename)
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.remove_index(filename, user_id=str(user.id), db_session=db)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to remove index"))
    return result


@router.post("/async/generate-quiz", response_model=AsyncJobResponse)
async def async_canvas_generate_quiz(
    request: CanvasGenerateQuizRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate quiz from Canvas documents asynchronously (non-blocking).
    """
    if not request.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")

    selected_documents = await _require_accessible_document_names(
        http_request,
        str(user.id),
        selected_documents=request.selected_documents,
    )

    try:
        job_service = JobService(db)
        payload = {
            "topics": request.topics,
            "num_questions": request.num_questions,
            "difficulty": request.difficulty,
            "language": request.language,
            "selected_documents": selected_documents,
            "user_id": str(user.id),
            "source": "canvas",
        }

        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.GENERATE_QUIZ,
            payload=payload,
        )
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
    except Exception:
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
    """
    await _check_canvas_permission(
        http_request,
        course_id=request.course_id,
        filename=request.filename,
        user_id=str(user.id),
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
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.rag_tasks.canvas_index_file,
            args=[str(job.id), request.filename],
            kwargs={
                "user_id": str(user.id),
                "course_id": request.course_id,
                "file_path": str(file_path),
            },
        )
        await job_service.set_celery_task_id(job.id, result.id)

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Indexing queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
    except Exception:
        logger.exception("Error queueing canvas index job")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")
