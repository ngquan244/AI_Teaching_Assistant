"""
Canvas LMS API Routes
Proxy endpoints for Canvas REST API with file download, MD5 deduplication, and QTI import
"""
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import CurrentUser
from backend.database import get_async_session
from backend.database.models.job import JobType
from backend.services.canvas_connection import resolve_canvas_connection_async
from backend.services.canvas_service import (
    fetch_canvas_courses,
    fetch_course_files,
    download_file_with_dedup,
    download_files_batch,
    import_qti_to_canvas,
)
from backend.services.job_service import JobService
from backend.services.url_safety import validate_download_url

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class FileDownloadRequest(BaseModel):
    file_id: int
    filename: str
    url: str
    course_id: int


class BatchDownloadRequest(BaseModel):
    course_id: int
    files: list[FileDownloadRequest]


class QTIImportRequest(BaseModel):
    """Request body for QTI import to Canvas"""
    course_id: int
    question_bank_name: str
    qti_zip_base64: str  # Base64 encoded zip file
    filename: Optional[str] = "qti_import.zip"


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/courses")
async def get_courses(
    http_request: Request,
    user: CurrentUser,
):
    """
    Proxy endpoint for Canvas GET /api/v1/users/self/courses
    """
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    result = await fetch_canvas_courses(token, base_url)
    
    if not result["success"]:
        raise HTTPException(
            status_code=401 if "Invalid" in result.get("error", "") else 500,
            detail=result.get("error", "Failed to fetch courses")
        )
    
    return result


@router.get("/courses/{course_id}/files")
async def get_course_files(
    course_id: int,
    http_request: Request,
    user: CurrentUser,
):
    """
    Proxy endpoint for Canvas GET /api/v1/courses/{course_id}/files
    """
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    result = await fetch_course_files(token, base_url, course_id)
    
    if not result["success"]:
        status_code = 401 if "Invalid" in result.get("error", "") else 500
        if "Access denied" in result.get("error", ""):
            status_code = 403
        raise HTTPException(
            status_code=status_code,
            detail=result.get("error", "Failed to fetch files")
        )
    
    return result


@router.post("/download")
async def download_single_file(
    request: FileDownloadRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Download a single file with MD5 deduplication
    
    The file is downloaded from the signed URL, MD5 hash is computed,
    and the file is saved only if no duplicate exists.
    
    Returns:
        - status: "saved" | "duplicate" | "failed"
        - md5_hash: computed hash (if successful)
        - saved_path: relative path where file was saved (if saved)
        - existing_file: path of duplicate (if duplicate)
    """
    await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )

    result = await download_file_with_dedup(
        file_id=request.file_id,
        filename=request.filename,
        download_url=validate_download_url(request.url),
        course_id=request.course_id,
    )
    
    return result


@router.post("/download/batch")
async def download_multiple_files(
    request: BatchDownloadRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Download multiple files with MD5 deduplication
    
    Processes files sequentially and returns summary statistics.
    
    Returns:
        - results: array of per-file results
        - total: total files processed
        - saved: files saved (unique)
        - duplicates: files skipped (duplicate)
        - failed: files that failed to download
    """
    await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    
    files_data = [
        {
            "file_id": f.file_id,
            "filename": f.filename,
            "url": validate_download_url(f.url),
        }
        for f in request.files
    ]
    
    result = await download_files_batch(
        course_id=request.course_id,
        files=files_data,
    )
    
    return result


@router.post("/import-qti-bank")
async def import_qti_bank(
    request: QTIImportRequest,
    http_request: Request,
    user: CurrentUser,
):
    """
    Import a QTI zip package into Canvas as a new Question Bank.
    
    This endpoint implements the full Canvas Content Migration flow:
    1. Create content migration with migration_type=qti_converter
    2. Upload the QTI zip to the pre_attachment URL (S3)
    3. Poll until migration completes
    
    Request body:
        - course_id: Target course ID
        - question_bank_name: Name for the new question bank
        - qti_zip_base64: Base64 encoded QTI zip file
        - filename: Optional filename (defaults to qti_import.zip)
    
    Returns:
        - success: boolean
        - status: 'completed' | 'failed'
        - migration_id: Canvas migration ID
        - message: Success/error message
    """
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    
    # Decode base64 zip content
    try:
        qti_zip_content = base64.b64decode(request.qti_zip_base64)
    except Exception as e:
        logger.warning("Invalid base64 zip input: %s", e)
        raise HTTPException(
            status_code=400,
            detail="Dữ liệu base64 không hợp lệ"
        )
    
    if len(qti_zip_content) == 0:
        raise HTTPException(
            status_code=400,
            detail="Empty zip file content"
        )
    
    # Perform import
    result = await import_qti_to_canvas(
        token=token,
        base_url=base_url,
        course_id=request.course_id,
        question_bank_name=request.question_bank_name,
        qti_zip_content=qti_zip_content,
        filename=request.filename or "qti_import.zip",
    )
    
    if not result["success"]:
        # Return error but don't raise exception for client to handle gracefully
        return {
            "success": False,
            "status": result.get("status", "failed"),
            "error": result.get("error", "Import failed"),
            "migration_id": result.get("migration_id"),
        }
    
    return result


# ============================================================================
# ASYNC JOB ENDPOINTS
# ============================================================================
# These endpoints return immediately with a job_id.
# The actual work is done in background via Celery.

from pydantic import BaseModel as PydanticBaseModel
from backend import tasks
from backend.celery_app import apply_async_nonblocking


class AsyncJobResponse(PydanticBaseModel):
    """Response for async job endpoints."""
    success: bool
    job_id: str
    message: str
    status_url: str
    stream_url: str


@router.post("/async/download")
async def async_download_single_file(
    request: FileDownloadRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Download a file asynchronously with MD5 deduplication.
    
    Returns immediately with job_id. Poll /api/jobs/{job_id} for status.
    """
    await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    safe_url = validate_download_url(request.url)
    
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.CANVAS_FILE_DOWNLOAD,
            payload={
                "file_id": request.file_id,
                "filename": request.filename,
                "url": safe_url,
                "course_id": request.course_id,
            },
        )

        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.canvas_tasks.download_file,
            args=[str(job.id)],
            kwargs={
                "file_id": request.file_id,
                "filename": request.filename,
                "download_url": safe_url,
                "course_id": request.course_id,
            },
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Download queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queuing file download")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/download/batch")
async def async_download_batch(
    request: BatchDownloadRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Download multiple files asynchronously.
    
    Returns immediately with job_id. Each file is processed sequentially
    with progress updates.
    """
    await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    
    try:
        job_service = JobService(db)
        
        files_data = [
            {
                "file_id": f.file_id,
                "filename": f.filename,
                "url": validate_download_url(f.url),
            }
            for f in request.files
        ]
        
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.CANVAS_FILE_DOWNLOAD,
            payload={"course_id": request.course_id, "files": files_data},
        )

        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.canvas_tasks.download_files_batch,
            args=[str(job.id), request.course_id, files_data],
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Batch download queued for {len(files_data)} files",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queuing batch download")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/import-qti-bank")
async def async_import_qti_bank(
    request: QTIImportRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Import QTI to Canvas asynchronously.
    
    Multi-step process: create migration -> upload zip -> poll completion.
    Returns immediately with job_id.
    """
    _, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    
    # Validate base64 up front
    try:
        import base64 as b64
        qti_zip_content = b64.b64decode(request.qti_zip_base64)
        if len(qti_zip_content) == 0:
            raise ValueError("Empty content")
    except Exception as e:
        logger.warning("Invalid base64 zip input: %s", e)
        raise HTTPException(status_code=400, detail="Dữ liệu base64 không hợp lệ")
    
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.CANVAS_QTI_IMPORT,
            payload={
                "course_id": request.course_id,
                "question_bank_name": request.question_bank_name,
                "filename": request.filename or "qti_import.zip",
            },
        )

        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.canvas_tasks.import_qti,
            args=[str(job.id)],
            kwargs={
                "course_id": request.course_id,
                "question_bank_name": request.question_bank_name,
                "qti_zip_base64": request.qti_zip_base64,
                "filename": request.filename or "qti_import.zip",
                "canvas_domain": base_url,
                "user_id": str(user.id),
            },
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"QTI import queued for course {request.course_id}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queuing QTI import")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")
