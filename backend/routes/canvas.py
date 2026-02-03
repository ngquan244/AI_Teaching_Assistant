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
