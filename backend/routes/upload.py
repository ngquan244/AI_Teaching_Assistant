"""
Upload API routes - File Upload Handling
"""
import logging
from fastapi import APIRouter, UploadFile, File
from typing import List

from backend.auth.dependencies import CurrentUser
from backend.schemas import UploadResponse
from backend.services import file_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/images", response_model=UploadResponse)
async def upload_exam_images(user: CurrentUser, files: List[UploadFile] = File(...)):
    """Upload exam images for grading"""
    uploaded_files, count = await file_service.upload_images(
        files, user_id=str(user.id)
    )
    
    return UploadResponse(
        success=count > 0,
        message=f"Đã upload {count} ảnh thành công",
        files=uploaded_files,
        count=count
    )


@router.get("/status")
def get_upload_status(user: CurrentUser):
    """Get current upload status"""
    return file_service.get_upload_status(user_id=str(user.id))


@router.delete("/images")
def clear_uploaded_images(user: CurrentUser):
    """Clear all uploaded images"""
    count = file_service.clear_images(user_id=str(user.id))
    return {
        "message": f"Đã xóa {count} ảnh",
        "success": True,
        "count": count
    }
