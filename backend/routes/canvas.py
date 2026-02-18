"""
Canvas LMS API Routes
Proxy endpoints for Canvas REST API with file download, MD5 deduplication, and QTI import
"""
import base64
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.services.canvas_service import (
    fetch_canvas_courses,
    fetch_course_files,
    download_file_with_dedup,
    download_files_batch,
    import_qti_to_canvas,
)

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
# Helper Functions
# ============================================================================

def get_canvas_credentials(
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
) -> tuple[str, str]:
    """Extract Canvas credentials from headers"""
    if not x_canvas_token:
        raise HTTPException(
            status_code=401,
            detail="Canvas access token not provided"
        )
    
    base_url = x_canvas_base_url or "https://lms.uet.vnu.edu.vn"
    return x_canvas_token, base_url


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/courses")
async def get_courses(
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """
    Proxy endpoint for Canvas GET /api/v1/users/self/courses
    
    Headers:
        X-Canvas-Token: Canvas access token
        X-Canvas-Base-Url: Canvas instance URL (optional, defaults to canvas.instructure.com)
    """
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
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
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """
    Proxy endpoint for Canvas GET /api/v1/courses/{course_id}/files
    
    Headers:
        X-Canvas-Token: Canvas access token
        X-Canvas-Base-Url: Canvas instance URL (optional)
    """
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
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
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
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
    # We don't need the token for downloading since the URL is pre-signed
    # But we validate credentials anyway for consistency
    get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    result = await download_file_with_dedup(
        file_id=request.file_id,
        filename=request.filename,
        download_url=request.url,
        course_id=request.course_id,
    )
    
    return result


@router.post("/download/batch")
async def download_multiple_files(
    request: BatchDownloadRequest,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
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
    get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    files_data = [
        {
            "file_id": f.file_id,
            "filename": f.filename,
            "url": f.url,
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
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
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
    
    Headers:
        - X-Canvas-Token: Canvas access token
        - X-Canvas-Base-Url: Canvas instance URL
    
    Returns:
        - success: boolean
        - status: 'completed' | 'failed'
        - migration_id: Canvas migration ID
        - message: Success/error message
    """
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    # Decode base64 zip content
    try:
        qti_zip_content = base64.b64decode(request.qti_zip_base64)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base64 encoded zip file: {str(e)}"
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

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from pydantic import BaseModel as PydanticBaseModel
from backend.database import get_async_session
from backend.services.job_service import JobService
from backend.database.models.job import JobType
from backend import tasks


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
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Download a file asynchronously with MD5 deduplication.
    
    Returns immediately with job_id. Poll /api/jobs/{job_id} for status.
    """
    get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=None,
            job_type=JobType.CANVAS_FILE_DOWNLOAD,
            payload={
                "file_id": request.file_id,
                "filename": request.filename,
                "url": request.url,
                "course_id": request.course_id,
            },
        )
        
        result = tasks.download_file.apply_async(
            args=[str(job.id)],
            kwargs={
                "file_id": request.file_id,
                "filename": request.filename,
                "download_url": request.url,
                "course_id": request.course_id,
            },
        )
        
        await job_service.update_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Download queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/download/batch")
async def async_download_batch(
    request: BatchDownloadRequest,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Download multiple files asynchronously.
    
    Returns immediately with job_id. Each file is processed sequentially
    with progress updates.
    """
    get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    try:
        job_service = JobService(db)
        
        files_data = [
            {"file_id": f.file_id, "filename": f.filename, "url": f.url}
            for f in request.files
        ]
        
        job = await job_service.create_job(
            user_id=None,
            job_type=JobType.CANVAS_FILE_DOWNLOAD,
            payload={"course_id": request.course_id, "files": files_data},
        )
        
        result = tasks.download_files_batch.apply_async(
            args=[str(job.id), request.course_id, files_data],
        )
        
        await job_service.update_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Batch download queued for {len(files_data)} files",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/async/import-qti-bank")
async def async_import_qti_bank(
    request: QTIImportRequest,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Import QTI to Canvas asynchronously.
    
    Multi-step process: create migration -> upload zip -> poll completion.
    Returns immediately with job_id.
    """
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    
    # Validate base64 up front
    try:
        import base64 as b64
        qti_zip_content = b64.b64decode(request.qti_zip_base64)
        if len(qti_zip_content) == 0:
            raise ValueError("Empty content")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 zip: {e}")
    
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=None,
            job_type=JobType.CANVAS_QTI_IMPORT,
            payload={
                "course_id": request.course_id,
                "question_bank_name": request.question_bank_name,
                "filename": request.filename or "qti_import.zip",
            },
        )
        
        result = tasks.import_qti.apply_async(
            args=[str(job.id)],
            kwargs={
                "token": token,
                "base_url": base_url,
                "course_id": request.course_id,
                "question_bank_name": request.question_bank_name,
                "qti_zip_base64": request.qti_zip_base64,
                "filename": request.filename or "qti_import.zip",
            },
        )
        
        await job_service.update_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"QTI import queued for course {request.course_id}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
