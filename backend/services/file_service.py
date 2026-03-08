"""
File Service
Handles file upload and management with per-user isolation
"""
import shutil
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from fastapi import UploadFile

from backend.core.config import settings
from backend.core import BadRequestException, FileLimits
from backend.utils import (
    ensure_directory,
    clear_directory,
    is_valid_image,
    safe_filename,
    get_user_upload_dir,
)

logger = logging.getLogger(__name__)


class FileService:
    """Service for file upload and management (per-user isolated)"""
    
    def _get_images_dir(self, user_id: str) -> Path:
        """Get the per-user images directory, creating it if needed."""
        return get_user_upload_dir(user_id)
    
    async def upload_images(
        self,
        files: List[UploadFile],
        user_id: str,
        clear_existing: bool = True
    ) -> Tuple[List[str], int]:
        """Upload exam images to the user's workspace"""
        images_dir = self._get_images_dir(user_id)
        
        if clear_existing:
            clear_directory(images_dir)
        
        uploaded = []
        for file in files:
            if not file.filename:
                continue
            
            if not is_valid_image(file.filename):
                logger.warning(f"Skipping invalid image: {file.filename}")
                continue
            
            # Check file size
            content = await file.read()
            if len(content) > FileLimits.MAX_IMAGE_SIZE:
                logger.warning(f"File too large: {file.filename}")
                continue
            
            # Save file
            filename = safe_filename(file.filename)
            dest_path = images_dir / filename
            
            with open(dest_path, "wb") as buffer:
                buffer.write(content)
            
            uploaded.append(filename)
            logger.info(f"Uploaded image: {filename} (user: {user_id})")
        
        return uploaded, len(uploaded)
    
    def get_upload_status(self, user_id: str) -> dict:
        """Get current upload status for a user"""
        images_dir = self._get_images_dir(user_id)
        images = list(images_dir.glob("*")) if images_dir.exists() else []
        
        return {
            "images": {
                "count": len([f for f in images if f.is_file()]),
                "files": [f.name for f in images if f.is_file()]
            }
        }
    
    def clear_images(self, user_id: str) -> int:
        """Clear all uploaded images for a user"""
        images_dir = self._get_images_dir(user_id)
        return clear_directory(images_dir)


# Singleton instance (stateless — safe to share)
file_service = FileService()
