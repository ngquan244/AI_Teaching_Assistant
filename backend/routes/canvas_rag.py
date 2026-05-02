"""
Canvas RAG API Routes
=====================
FastAPI routes for Canvas-specific Document RAG features.
Completely separate from uploaded document routes.
"""

import asyncio
import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional

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
from backend.modules.document_rag.rag_repository import (
    RAGCollectionRepository,
    SyncRAGCollectionRepository,
    SyncCanvasCourseDomainDocRepository,
)
from backend.services.canvas_connection import resolve_canvas_connection_async
from backend.services.canvas_permission import canvas_permission
from backend.services.canvas_service import fetch_canvas_courses
from backend.services.job_service import JobService
from backend.services.url_safety import validate_download_url
from backend.routes.document_rag import _generate_quiz_idempotency_key
from backend.core.config import settings
from backend.core.security import decrypt_token
from backend.database.models import AppSetting

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_groq_api_key(db_session) -> Optional[str]:
    """Resolve the latest Groq API key from DB or env."""
    try:
        record = db_session.get(AppSetting, "GROQ_API_KEY")
        if record and record.value:
            encrypted = record.value.get("encrypted")
            if encrypted:
                return decrypt_token(encrypted)
    except Exception:
        pass
    env_key = settings.GROQ_API_KEY
    return env_key.strip() if env_key and env_key.strip() else None


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
    # ── V1: course-level shared domain knowledge ───────────────────────
    include_course_domain: bool = True
    domain_quota_ratio: Optional[float] = None  # clamped to [0.0, 0.6] downstream


class AsyncJobResponse(BaseModel):
    """Response for async job endpoints."""
    success: bool
    job_id: str
    message: str
    status_url: str
    stream_url: str


def _resolve_course_id_for_filename(filename: str, user_id: str) -> Optional[int]:
    """Look up course_id for a filename from the rag_collections table (sync)."""
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


async def _resolve_course_id_for_filename_async(
    filename: str, user_id: str, db: AsyncSession,
) -> Optional[int]:
    """Look up course_id for a filename (async — no thread hop)."""
    try:
        rows = await RAGCollectionRepository.get_by_filenames(
            db, [filename], _uuid.UUID(user_id), source=RAGSourceType.CANVAS,
        )
        if rows and rows[0].course_id:
            return rows[0].course_id
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
    # Run sync DB/file I/O off the event loop and resolve Canvas token concurrently
    docs_future = asyncio.to_thread(_list_canvas_documents_for_user, user_id)
    token_future = resolve_canvas_connection_async(
        user_id=user_id,
        request=request,
        require=False,
    )
    docs, (canvas_token, canvas_base_url) = await asyncio.gather(
        docs_future, token_future,
    )

    if selected_documents is not None:
        selected_set = set(selected_documents)
        docs = [doc for doc in docs if doc.get("filename") in selected_set]

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
    *,
    require_privileged_role: bool = False,
) -> None:
    """Validate the active Canvas connection can access the relevant course.

    When ``require_privileged_role=True`` the token must additionally hold
    a teacher / TA / designer enrollment on the course (V2 mark/unmark).
    """
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
    if require_privileged_role:
        await canvas_permission.require_privileged_role(canvas_base_url, canvas_token, cid)


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


@router.post("/extract-topics", deprecated=True)
async def extract_topics_for_canvas_file(
    request: CanvasExtractTopicsRequest,
    http_request: Request,
    user: CurrentUser,
):
    """Extract topics from an indexed Canvas file."""
    logger.warning("DEPRECATED sync endpoint /extract-topics called - migrate to /async/extract-topics")
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
        with SessionLocal() as db:
            groq_key = _resolve_groq_api_key(db)
            return service.extract_topics_for_file(
                filename,
                num_topics,
                user_id=user_id,
                db_session=db,
                groq_api_key=groq_key,
            )

    return await asyncio.to_thread(_do_extract)


@router.get("/topics/{filename}")
async def get_canvas_document_topics(
    filename: str,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """Get topics for a Canvas document."""
    user_id = str(user.id)

    # Permission check using async DB (avoids sync thread hop)
    cid = await _resolve_course_id_for_filename_async(filename, user_id, db)
    if cid is not None:
        canvas_token, canvas_base_url = await resolve_canvas_connection_async(
            user_id=user_id, request=http_request, require=False,
        )
        if canvas_token and canvas_base_url:
            await canvas_permission.validate_course_access(canvas_base_url, canvas_token, cid)
        elif cid is not None:
            raise HTTPException(
                status_code=403,
                detail="Canvas token required to access course-scoped data. Please connect a Canvas token in Settings.",
            )

    try:
        # Try async DB first — fast path, no thread hop
        topics = await RAGCollectionRepository.get_topics_by_filename(
            db, filename, _uuid.UUID(user_id), source=RAGSourceType.CANVAS,
        )
        if topics is not None:
            names = [t["name"] if isinstance(t, dict) else t for t in topics]
            return {"success": True, "topics": names, "filename": filename}

        # Fallback to legacy file-based topic storage (sync)
        def _fallback():
            service = get_canvas_rag_service()
            service._ensure_topic_storage()
            raw = service._topic_storage.get_topics_by_filename(filename, user_id=user_id)
            if raw:
                return [t["name"] if isinstance(t, dict) else t for t in raw]
            return []

        names = await asyncio.to_thread(_fallback)
        return {"success": True, "topics": names, "filename": filename}
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

    Fast path when ``course_id`` is given: validate just that one course and
    filter the user's docs locally. This avoids:
      - calling Canvas ``filter_accessible_courses`` over every other course
        the user has ever indexed
      - calling Canvas ``fetch_canvas_courses`` only to attach a name
        (the frontend already knows the selected course name)
    """
    try:
        user_id = str(user.id)

        # ── Fast path: a specific course was requested ─────────────────
        if course_id is not None:
            await _check_canvas_permission(
                http_request, course_id=course_id, user_id=user_id,
            )
            all_docs = await asyncio.to_thread(
                _list_canvas_documents_for_user, user_id,
            )
            docs = [d for d in all_docs if d.get("course_id") == course_id]

            total = len(docs)
            offset = (page - 1) * page_size
            paged_docs = docs[offset:offset + page_size]
            # No course_name enrichment — frontend already has it for the
            # selected course. Saves one Canvas API roundtrip per call.
            return {
                "success": True,
                "documents": paged_docs,
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size if total else 1,
            }

        # ── General path (no course_id): preserve original semantics ────
        docs, canvas_token, canvas_base_url = await _get_accessible_canvas_documents(
            http_request,
            user_id,
        )

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
    with SessionLocal() as db:
        stats = service.get_index_stats(user_id=str(user.id), db_session=db)
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
                include_course_domain=req.include_course_domain,
                domain_quota_ratio=req.domain_quota_ratio,
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
            "include_course_domain": request.include_course_domain,
            "domain_quota_ratio": request.domain_quota_ratio,
        }

        # Idempotency: dedupe accidental double-clicks within the in-flight window.
        idem_key = _generate_quiz_idempotency_key(
            scope="canvas",
            user_id=str(user.id),
            topics=request.topics,
            num_questions=request.num_questions,
            difficulty=request.difficulty,
            language=request.language,
            selected_documents=selected_documents,
            extra={
                "include_course_domain": bool(request.include_course_domain),
                "domain_quota_ratio": request.domain_quota_ratio,
            },
        )
        job, created = await job_service.get_or_create_job(
            user_id=user.id,
            job_type=JobType.GENERATE_QUIZ,
            idempotency_key=idem_key,
            payload=payload,
        )
        await db.commit()

        if created:
            result = await apply_async_nonblocking(
                tasks.llm_tasks.generate_quiz,
                args=[str(job.id)],
                kwargs=payload,
            )
            await job_service.set_celery_task_id(job.id, result.id)
            message = f"Canvas quiz generation queued for topics: {', '.join(request.topics)}"
        else:
            logger.info(f"Reusing in-flight canvas quiz job {job.id} for idempotency_key={idem_key[:12]}…")
            message = "Yêu cầu tạo quiz tương tự đang chạy, đang theo dõi job hiện có."

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=message,
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


@router.post("/async/extract-topics", response_model=AsyncJobResponse)
async def async_extract_topics(
    request: CanvasExtractTopicsRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Extract topics from a Canvas file asynchronously (non-blocking).
    Delegates heavy embedding work to the rag worker.
    """
    await _check_canvas_permission(
        http_request,
        filename=request.filename,
        user_id=str(user.id),
    )

    try:
        job_service = JobService(db)
        payload = {
            "filename": request.filename,
            "num_topics": request.num_topics,
            "user_id": str(user.id),
        }

        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.CANVAS_EXTRACT_TOPICS,
            payload=payload,
        )
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.rag_tasks.canvas_extract_topics,
            args=[str(job.id), request.filename],
            kwargs={
                "num_topics": request.num_topics,
                "user_id": str(user.id),
            },
        )
        await job_service.set_celery_task_id(job.id, result.id)

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Topic extraction queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
    except Exception:
        logger.exception("Error queueing canvas extract topics job")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


# =====================================================================
# V1: Course-level shared domain knowledge (feature flag gated)
# =====================================================================

class CourseDomainDocsMarkRequest(BaseModel):
    """Mark a list of indexed Canvas files as course-level shared domain docs."""
    file_hashes: List[str]


@router.get("/courses/{course_id}/documents")
async def list_course_documents(
    course_id: int,
    http_request: Request,
    user: CurrentUser,
):
    """List indexed documents for a course, enriched with `language` and
    `is_course_domain` flags (V1 course-domain feature)."""
    await _check_canvas_permission(
        http_request, course_id=course_id, user_id=str(user.id),
    )
    user_id = str(user.id)

    def _do() -> Dict[str, Any]:
        service = get_canvas_rag_service()
        with SessionLocal() as db:
            listed = service.list_indexed_documents(user_id=user_id, db_session=db)
            documents = [
                d for d in listed.get("documents", [])
                if d.get("course_id") == course_id
            ]
            hashes = [d["file_hash"] for d in documents if d.get("file_hash")]

            language_map: Dict[str, Optional[str]] = {}
            try:
                language_map = SyncRAGCollectionRepository.get_language_by_hashes(db, hashes)
            except Exception as exc:
                logger.warning("get_language_by_hashes failed: %s", exc)
                db.rollback()

            domain_set: set = set()
            domain_rows: List[Any] = []
            try:
                domain_set = SyncCanvasCourseDomainDocRepository.get_marked_subset(
                    db, course_id, hashes,
                )
                domain_rows = SyncCanvasCourseDomainDocRepository.list_for_course(
                    db, course_id, include_disabled=False,
                )
            except Exception as exc:
                logger.warning("course domain marks lookup failed: %s", exc)
                db.rollback()
            marked_by_map = {row.file_hash: row.marked_by_user_id for row in domain_rows}

            for d in documents:
                fh = d.get("file_hash")
                d["language"] = language_map.get(fh)
                d["is_course_domain"] = fh in domain_set
                marker = marked_by_map.get(fh)
                d["marked_by_user_id"] = str(marker) if marker is not None else None

            return {"success": True, "documents": documents, "count": len(documents)}

    return await asyncio.to_thread(_do)


@router.post("/courses/{course_id}/domain-documents")
async def mark_course_domain_documents(
    course_id: int,
    body: CourseDomainDocsMarkRequest,
    http_request: Request,
    user: CurrentUser,
):
    """Mark indexed Canvas files as course-level shared domain knowledge.

    **Eligibility rule (binding):** only documents indexed through the
    Canvas course-document pipeline (``source=CANVAS``) AND belonging to
    the target course are eligible. The request is **atomic** — if any
    requested hash is ineligible, no rows are inserted.
    """
    if not getattr(settings, "ENABLE_COURSE_DOMAIN_DOCS", False):
        raise HTTPException(
            status_code=403,
            detail={"error": "FEATURE_DISABLED", "message": "Course-domain feature is disabled"},
        )

    await _check_canvas_permission(
        http_request,
        course_id=course_id,
        user_id=str(user.id),
        require_privileged_role=True,
    )
    if not body.file_hashes:
        raise HTTPException(
            status_code=400,
            detail={"error": "EMPTY_PAYLOAD", "message": "file_hashes is required"},
        )

    file_hashes = list({h for h in body.file_hashes if h})
    if not file_hashes:
        raise HTTPException(
            status_code=400,
            detail={"error": "EMPTY_PAYLOAD", "message": "file_hashes is required"},
        )

    user_uuid = user.id

    def _validate_and_mark():
        with SessionLocal() as db:
            try:
                # ── Eligibility check (Canvas-only + same course) ──
                rows = SyncRAGCollectionRepository.get_by_hashes(
                    db, file_hashes, source=RAGSourceType.CANVAS,
                )
                eligible_by_hash = {r.file_hash: r for r in rows}
                not_canvas = [h for h in file_hashes if h not in eligible_by_hash]
                if not_canvas:
                    return {
                        "_error": {
                            "error": "NOT_CANVAS_DOC",
                            "ineligible_hashes": not_canvas,
                            "message": (
                                "Only documents indexed through the Canvas "
                                "course-document pipeline can be marked as "
                                "course domain knowledge."
                            ),
                        },
                        "_status": 400,
                    }
                wrong_course = [
                    h for h, r in eligible_by_hash.items()
                    if r.course_id is not None and r.course_id != course_id
                ]
                if wrong_course:
                    return {
                        "_error": {
                            "error": "WRONG_COURSE",
                            "ineligible_hashes": wrong_course,
                            "message": (
                                f"One or more files belong to a different "
                                f"Canvas course than {course_id}."
                            ),
                        },
                        "_status": 400,
                    }

                # ── Atomic upsert ──
                inserted = SyncCanvasCourseDomainDocRepository.upsert_many(
                    db,
                    course_id=course_id,
                    file_hashes=file_hashes,
                    marked_by_user_id=user_uuid,
                )
                db.commit()
                return {"_inserted": inserted}
            except Exception:
                db.rollback()
                raise

    try:
        result = await asyncio.to_thread(_validate_and_mark)
    except Exception as exc:
        logger.exception("mark_course_domain_documents failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL", "message": str(exc)},
        )

    if "_error" in result:
        raise HTTPException(status_code=result["_status"], detail=result["_error"])

    return {
        "success": True,
        "course_id": course_id,
        "marked_count": result["_inserted"],
        "file_hashes": file_hashes,
    }


@router.delete("/courses/{course_id}/domain-documents/{file_hash}")
async def unmark_course_domain_document(
    course_id: int,
    file_hash: str,
    http_request: Request,
    user: CurrentUser,
):
    """Soft-delete (disable) a course-domain mark for a given file.

    The file_hash must correspond to an existing **enabled** mark on the
    target course; otherwise 404.
    """
    if not getattr(settings, "ENABLE_COURSE_DOMAIN_DOCS", False):
        raise HTTPException(
            status_code=403,
            detail={"error": "FEATURE_DISABLED", "message": "Course-domain feature is disabled"},
        )

    await _check_canvas_permission(
        http_request,
        course_id=course_id,
        user_id=str(user.id),
        require_privileged_role=True,
    )

    def _do() -> bool:
        with SessionLocal() as db:
            try:
                ok = SyncCanvasCourseDomainDocRepository.disable(
                    db,
                    course_id=course_id,
                    file_hash=file_hash,
                )
                db.commit()
                return ok
            except Exception:
                db.rollback()
                raise

    try:
        ok = await asyncio.to_thread(_do)
    except Exception as exc:
        logger.exception("unmark_course_domain_document failed")
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL", "message": str(exc)},
        )

    if not ok:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "NOT_FOUND",
                "message": "Domain mark not found for this course/file_hash.",
            },
        )
    return {"success": True, "course_id": course_id, "file_hash": file_hash}


@router.get("/courses/{course_id}/domain-documents")
async def list_course_domain_documents(
    course_id: int,
    http_request: Request,
    user: CurrentUser,
    include_disabled: bool = Query(False),
):
    """List the course-level shared domain marks for a course."""
    await _check_canvas_permission(
        http_request, course_id=course_id, user_id=str(user.id),
    )

    def _do():
        with SessionLocal() as db:
            return SyncCanvasCourseDomainDocRepository.list_for_course(
                db, course_id, include_disabled=include_disabled,
            )

    rows = await asyncio.to_thread(_do)
    return {
        "success": True,
        "course_id": course_id,
        "domain_documents": [r.to_dict() for r in rows],
        "count": len(rows),
    }

