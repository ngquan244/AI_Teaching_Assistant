"""
Guide API Routes
================
Serves per-panel guide documents from the database.
Admin can create, update, delete guide documents and upload images.
Non-admin users see only published guides for visible panels.
"""
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import CurrentUser, AdminUser
from backend.database.base import get_async_session
from backend.database.models.user import UserRole
from backend.services import guide_service
from backend.services.panel_config_service import get_panel_config
from backend.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# Allowed image MIME types and extensions
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


# ─── Schemas ──────────────────────────────────────────────────────────

class GuideListItem(BaseModel):
    """Summary of a guide document for the listing."""
    panel_key: str
    title: str
    description: Optional[str] = None
    icon_name: Optional[str] = None
    sort_order: int = 0
    is_published: bool = True

    class Config:
        from_attributes = True


class GuideListResponse(BaseModel):
    guides: List[GuideListItem]
    success: bool = True


class GuideDetailResponse(BaseModel):
    panel_key: str
    title: str
    description: Optional[str] = None
    icon_name: Optional[str] = None
    content: str
    sort_order: int = 0
    is_published: bool = True
    success: bool = True

    class Config:
        from_attributes = True


class GuideUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    icon_name: Optional[str] = None
    content: Optional[str] = None
    sort_order: Optional[int] = None
    is_published: Optional[bool] = None


class GuideCreateRequest(BaseModel):
    panel_key: str
    title: str
    content: str = ""
    description: Optional[str] = None
    icon_name: Optional[str] = None
    sort_order: int = 0
    is_published: bool = True


class ImageUploadResponse(BaseModel):
    url: str
    filename: str
    success: bool = True


# ─── Helpers ──────────────────────────────────────────────────────────

def _get_visible_panels() -> set[str]:
    """Get the set of panel keys that are currently enabled."""
    config = get_panel_config()
    return {k for k, v in config.items() if v}


# ─── Endpoints ────────────────────────────────────────────────────────

@router.get("", response_model=GuideListResponse)
async def list_guides(
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    List all guide documents.
    Non-admin users only see published guides for visible panels.
    """
    is_admin = user.role == UserRole.ADMIN

    if is_admin:
        guides = await guide_service.list_guides(db, include_unpublished=True)
    else:
        visible = _get_visible_panels()
        guides = await guide_service.list_guides(
            db, include_unpublished=False, visible_panels=visible
        )

    items = [
        GuideListItem(
            panel_key=g.panel_key,
            title=g.title,
            description=g.description,
            icon_name=g.icon_name,
            sort_order=g.sort_order,
            is_published=g.is_published,
        )
        for g in guides
    ]
    return GuideListResponse(guides=items)


@router.get("/{panel_key}", response_model=GuideDetailResponse)
async def get_guide(
    panel_key: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get full content of a guide document by panel_key.
    Non-admin users can only view published guides for visible panels.
    """
    guide = await guide_service.get_guide_by_panel_key(db, panel_key)
    if not guide:
        raise HTTPException(status_code=404, detail="Guide document not found")

    is_admin = user.role == UserRole.ADMIN

    if not is_admin:
        if not guide.is_published:
            raise HTTPException(status_code=404, detail="Guide document not found")

        # Check panel visibility (overview and faq are always accessible)
        always_visible = {"overview", "faq"}
        if panel_key not in always_visible:
            visible = _get_visible_panels()
            if panel_key not in visible:
                raise HTTPException(
                    status_code=403,
                    detail="This guide is not available for your current configuration"
                )

    return GuideDetailResponse(
        panel_key=guide.panel_key,
        title=guide.title,
        description=guide.description,
        icon_name=guide.icon_name,
        content=guide.content,
        sort_order=guide.sort_order,
        is_published=guide.is_published,
    )


@router.post("", response_model=GuideDetailResponse, status_code=201)
async def create_guide_endpoint(
    request: GuideCreateRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    """Create a new guide document (admin only)."""
    # Check if panel_key already exists
    existing = await guide_service.get_guide_by_panel_key(db, request.panel_key)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Guide for panel '{request.panel_key}' already exists"
        )

    guide = await guide_service.create_guide(
        db,
        panel_key=request.panel_key,
        title=request.title,
        content=request.content,
        description=request.description,
        icon_name=request.icon_name,
        sort_order=request.sort_order,
        is_published=request.is_published,
    )
    await db.commit()

    return GuideDetailResponse(
        panel_key=guide.panel_key,
        title=guide.title,
        description=guide.description,
        icon_name=guide.icon_name,
        content=guide.content,
        sort_order=guide.sort_order,
        is_published=guide.is_published,
    )


@router.put("/{panel_key}", response_model=GuideDetailResponse)
async def update_guide_endpoint(
    panel_key: str,
    request: GuideUpdateRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    """Update a guide document (admin only). Only non-null fields are updated."""
    guide = await guide_service.update_guide(
        db,
        panel_key,
        title=request.title,
        content=request.content,
        description=request.description,
        icon_name=request.icon_name,
        sort_order=request.sort_order,
        is_published=request.is_published,
    )
    if not guide:
        raise HTTPException(status_code=404, detail="Guide document not found")

    await db.commit()

    return GuideDetailResponse(
        panel_key=guide.panel_key,
        title=guide.title,
        description=guide.description,
        icon_name=guide.icon_name,
        content=guide.content,
        sort_order=guide.sort_order,
        is_published=guide.is_published,
    )


@router.delete("/{panel_key}")
async def delete_guide_endpoint(
    panel_key: str,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_async_session),
):
    """Delete a guide document (admin only)."""
    deleted = await guide_service.delete_guide(db, panel_key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Guide document not found")

    await db.commit()
    return {"success": True, "message": f"Guide '{panel_key}' deleted"}


@router.post("/images", response_model=ImageUploadResponse)
async def upload_guide_image(
    _admin: AdminUser,
    file: UploadFile = File(...),
):
    """
    Upload an image for use in guide markdown content (admin only).
    Returns the URL to embed in markdown: ![alt](/media/guide/filename.png)
    """
    # Validate content type
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image type: {file.content_type}. "
                   f"Allowed: {', '.join(_ALLOWED_IMAGE_TYPES)}"
        )

    # Validate extension
    original_name = file.filename or "image.png"
    ext = Path(original_name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension: {ext}"
        )

    # Read and validate size
    content = await file.read()
    if len(content) > _MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(content) / 1024 / 1024:.1f} MB). "
                   f"Max: {_MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB"
        )

    # Generate unique filename
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.GUIDE_IMAGES_DIR / unique_name

    # Write to disk
    settings.GUIDE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    url = f"/media/guide/{unique_name}"
    logger.info("Guide image uploaded: %s (%d bytes)", unique_name, len(content))

    return ImageUploadResponse(url=url, filename=unique_name)
