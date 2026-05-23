"""
Admin API Routes
================
REST endpoints for administrative operations.
All endpoints require ADMIN role.
"""
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, UserRole, UserStatus
from backend.auth.dependencies import AdminUser
from backend.services.admin_service import AdminService
from backend.services.invite_code_service import InviteCodeService
from backend.services import app_settings_service
from backend.services.panel_config_service import (
    get_panel_config,
    update_panel_config,
    PANEL_LABELS,
    ALL_PANELS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# =============================================================================
# Schemas
# =============================================================================

class AdminUserOut(BaseModel):
    """User output for admin views."""
    id: str
    email: str
    name: str
    role: str
    status: str
    created_at: str
    updated_at: Optional[str] = None
    last_login_at: Optional[str] = None

    class Config:
        from_attributes = True


class AdminUserListOut(BaseModel):
    """Paginated user list."""
    items: List[AdminUserOut]
    total: int
    page: int
    page_size: int
    pages: int


class UpdateUserRequest(BaseModel):
    """Request to update a user."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[str] = Field(None, description="ADMIN or TEACHER")
    status: Optional[str] = Field(None, description="ACTIVE, DISABLED, or PENDING")


class ResetPasswordRequest(BaseModel):
    """Request to reset a user's password."""
    new_password: str = Field(..., min_length=8, max_length=128)


class AdminJobOut(BaseModel):
    """Job output with user info for admin views."""
    id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    job_type: str
    status: str
    progress_pct: int
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class AdminJobListOut(BaseModel):
    """Paginated job list for admin."""
    items: List[AdminJobOut]
    total: int
    page: int
    page_size: int
    pages: int


class DashboardStatsOut(BaseModel):
    """Dashboard statistics."""
    users: dict
    jobs: dict
    canvas_tokens: dict


class MessageOut(BaseModel):
    success: bool
    message: str


# =============================================================================
# Helper
# =============================================================================

def _user_to_out(user) -> AdminUserOut:
    return AdminUserOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role.value if hasattr(user.role, "value") else str(user.role),
        status=user.status.value if hasattr(user.status, "value") else str(user.status),
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None,
    )


# =============================================================================
# Dashboard
# =============================================================================

@router.get("/dashboard", response_model=DashboardStatsOut)
async def get_dashboard_stats(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get system-wide statistics for the admin dashboard."""
    service = AdminService(db)
    stats = await service.get_dashboard_stats()
    return DashboardStatsOut(**stats)


# =============================================================================
# User Management
# =============================================================================

@router.get("/users", response_model=AdminUserListOut)
async def list_users(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[str] = Query(None, description="Filter by role: ADMIN, TEACHER"),
    status: Optional[str] = Query(None, description="Filter by status: ACTIVE, DISABLED, PENDING"),
    search: Optional[str] = Query(None, description="Search by email or name"),
):
    """List all users with filtering and pagination."""
    role_enum = None
    if role:
        try:
            role_enum = UserRole(role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

    status_enum = None
    if status:
        try:
            status_enum = UserStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    service = AdminService(db)
    users, total = await service.list_users(
        page=page,
        page_size=page_size,
        role=role_enum,
        status=status_enum,
        search=search,
    )

    return AdminUserListOut(
        items=[_user_to_out(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


@router.get("/users/{user_id}", response_model=AdminUserOut)
async def get_user(
    user_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a single user's details."""
    service = AdminService(db)
    user = await service.get_user(user_id)
    return _user_to_out(user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update user role, status, or name."""
    role_enum = None
    if body.role:
        try:
            role_enum = UserRole(body.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {body.role}")

    status_enum = None
    if body.status:
        try:
            status_enum = UserStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    service = AdminService(db)
    user = await service.update_user(
        user_id,
        name=body.name,
        role=role_enum,
        status=status_enum,
    )
    return _user_to_out(user)


@router.post("/users/{user_id}/reset-password", response_model=MessageOut)
async def reset_user_password(
    user_id: UUID,
    body: ResetPasswordRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password."""
    service = AdminService(db)
    await service.reset_user_password(user_id, body.new_password)
    return MessageOut(success=True, message="Password reset successfully")


@router.delete("/users/{user_id}", response_model=MessageOut)
async def delete_user(
    user_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete a user. Cannot delete yourself."""
    service = AdminService(db)
    await service.delete_user(user_id, admin.id)
    return MessageOut(success=True, message="User deleted successfully")


# =============================================================================
# Job Management (all users)
# =============================================================================

@router.get("/jobs", response_model=AdminJobListOut)
async def list_all_jobs(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None, description="Filter by user ID"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """List all jobs across all users with filtering."""
    service = AdminService(db)
    jobs, total = await service.list_all_jobs(
        page=page,
        page_size=page_size,
        user_id=user_id,
        job_type=job_type,
        status=status,
    )

    return AdminJobListOut(
        items=[AdminJobOut(**j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size if total > 0 else 1,
    )


# =============================================================================
# Panel Visibility Management
# =============================================================================

class PanelConfigOut(BaseModel):
    """Current panel visibility configuration."""
    panels: dict  # { "chat": true, "upload": false, ... }
    labels: dict  # { "chat": "Chat AI", ... }
    all_panels: List[str]  # ordered list of panel keys


class UpdatePanelConfigRequest(BaseModel):
    """Request to update panel visibility."""
    panels: dict  # { "chat": true, "upload": false, ... }


@router.get("/panels", response_model=PanelConfigOut)
async def get_panels(admin: AdminUser):
    """Get current panel visibility configuration."""
    config = get_panel_config()
    return PanelConfigOut(
        panels=config,
        labels=PANEL_LABELS,
        all_panels=ALL_PANELS,
    )


@router.put("/panels", response_model=PanelConfigOut)
async def update_panels(
    body: UpdatePanelConfigRequest,
    admin: AdminUser,
):
    """Update panel visibility. Only admin can toggle panels on/off."""
    config = update_panel_config(body.panels)
    logger.info("Admin %s updated panel config: %s", admin.email, config)
    return PanelConfigOut(
        panels=config,
        labels=PANEL_LABELS,
        all_panels=ALL_PANELS,
    )


# =============================================================================
# Invite Code Schemas
# =============================================================================

class InviteCodeOut(BaseModel):
    """Invite code output (never includes the full plaintext)."""
    id: str
    code_prefix: str
    label: Optional[str] = None
    max_uses: Optional[int] = None
    used_count: int
    is_active: bool
    is_usable: bool
    expires_at: Optional[str] = None
    created_by_email: Optional[str] = None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class InviteCodeCreatedOut(InviteCodeOut):
    """Returned exactly once at creation — includes the plaintext code."""
    plaintext_code: str


class InviteCodeListOut(BaseModel):
    """Paginated invite code list."""
    items: List[InviteCodeOut]
    total: int
    page: int
    page_size: int
    pages: int


class CreateInviteCodeRequest(BaseModel):
    """Request to create a new invite code."""
    label: Optional[str] = Field(None, max_length=100)
    max_uses: Optional[int] = Field(None, ge=1)
    expires_at: Optional[datetime] = None


class UpdateInviteCodeRequest(BaseModel):
    """Request to update an invite code."""
    label: Optional[str] = Field(None, max_length=100)
    max_uses: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    expires_at: Optional[datetime] = None


class InviteCodeUsageOut(BaseModel):
    """Usage record output."""
    id: str
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    used_at: str


class InviteCodeUsageListOut(BaseModel):
    """Paginated usage list."""
    items: List[InviteCodeUsageOut]
    total: int
    page: int
    page_size: int
    pages: int


class InviteCodeStatsOut(BaseModel):
    """Summary statistics."""
    total_codes: int
    active_codes: int
    total_usages: int


class SignupSettingsOut(BaseModel):
    """Current signup settings."""
    mode: str


class UpdateSignupSettingsRequest(BaseModel):
    """Request to update signup settings."""
    mode: str = Field(..., description="open | invite | closed")


# =============================================================================
# Invite Code Helpers
# =============================================================================

def _invite_code_to_out(invite) -> InviteCodeOut:
    return InviteCodeOut(
        id=str(invite.id),
        code_prefix=invite.code_prefix,
        label=invite.label,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        is_active=invite.is_active,
        is_usable=invite.is_usable,
        expires_at=invite.expires_at.isoformat() if invite.expires_at else None,
        created_by_email=invite.creator.email if invite.creator else None,
        created_at=invite.created_at.isoformat(),
        updated_at=invite.updated_at.isoformat(),
    )


# =============================================================================
# Signup Settings Endpoints
# =============================================================================

@router.get("/signup-settings", response_model=SignupSettingsOut)
async def get_signup_settings(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get current signup mode from DB (falls back to env var)."""
    mode = await app_settings_service.get_signup_mode(db)
    return SignupSettingsOut(mode=mode)


@router.put("/signup-settings", response_model=SignupSettingsOut)
async def update_signup_settings(
    body: UpdateSignupSettingsRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update the signup mode at runtime (persisted in DB)."""
    allowed = {"open", "invite", "closed"}
    if body.mode not in allowed:
        raise HTTPException(400, f"mode phải là một trong {allowed}")
    await app_settings_service.set_setting(db, "SIGNUP_MODE", body.mode)
    logger.info("Admin %s changed SIGNUP_MODE to '%s'", admin.email, body.mode)
    return SignupSettingsOut(mode=body.mode)


# =============================================================================
# Invite Code Endpoints
# =============================================================================

@router.get("/invite-codes/stats", response_model=InviteCodeStatsOut)
async def get_invite_code_stats(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get invite code summary statistics."""
    svc = InviteCodeService(db)
    stats = await svc.get_stats()
    return InviteCodeStatsOut(**stats)


@router.get("/invite-codes", response_model=InviteCodeListOut)
async def list_invite_codes(
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """List invite codes with pagination."""
    svc = InviteCodeService(db)
    codes, total = await svc.list_codes(page, page_size, active_only)
    pages = (total + page_size - 1) // page_size if total else 0
    return InviteCodeListOut(
        items=[_invite_code_to_out(c) for c in codes],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post("/invite-codes", response_model=InviteCodeCreatedOut, status_code=201)
async def create_invite_code(
    body: CreateInviteCodeRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new invite code.
    The plaintext_code is returned exactly ONCE — store it securely.
    """
    svc = InviteCodeService(db)
    invite, plaintext = await svc.create_code(
        created_by=admin.id,
        label=body.label,
        max_uses=body.max_uses,
        expires_at=body.expires_at,
    )
    logger.info(
        "Admin %s created invite code %s (prefix=%s)",
        admin.email, invite.id, invite.code_prefix,
    )
    out = _invite_code_to_out(invite)
    return InviteCodeCreatedOut(**out.model_dump(), plaintext_code=plaintext)


@router.get("/invite-codes/{code_id}", response_model=InviteCodeOut)
async def get_invite_code(
    code_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get a single invite code by ID."""
    svc = InviteCodeService(db)
    invite = await svc.get_code(code_id)
    return _invite_code_to_out(invite)


@router.patch("/invite-codes/{code_id}", response_model=InviteCodeOut)
async def update_invite_code(
    code_id: UUID,
    body: UpdateInviteCodeRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update an invite code's editable fields."""
    svc = InviteCodeService(db)
    kwargs = {}
    if body.label is not None:
        kwargs["label"] = body.label
    if body.max_uses is not None:
        kwargs["max_uses"] = body.max_uses
    if body.is_active is not None:
        kwargs["is_active"] = body.is_active
    if body.expires_at is not None:
        kwargs["expires_at"] = body.expires_at

    invite = await svc.update_code(code_id, **kwargs)
    logger.info("Admin %s updated invite code %s", admin.email, code_id)
    return _invite_code_to_out(invite)


@router.post("/invite-codes/{code_id}/toggle", response_model=InviteCodeOut)
async def toggle_invite_code(
    code_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Toggle an invite code's active status."""
    svc = InviteCodeService(db)
    invite = await svc.toggle_active(code_id)
    logger.info(
        "Admin %s toggled invite code %s -> active=%s",
        admin.email, code_id, invite.is_active,
    )
    return _invite_code_to_out(invite)


@router.delete("/invite-codes/{code_id}", response_model=MessageOut)
async def delete_invite_code(
    code_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete an invite code and all its usage records."""
    svc = InviteCodeService(db)
    await svc.delete_code(code_id)
    logger.info("Admin %s deleted invite code %s", admin.email, code_id)
    return MessageOut(success=True, message="Đã xoá mã mời.")


@router.get("/invite-codes/{code_id}/usages", response_model=InviteCodeUsageListOut)
async def get_invite_code_usages(
    code_id: UUID,
    admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get usage records for a specific invite code."""
    svc = InviteCodeService(db)
    usages, total = await svc.get_usages(code_id, page, page_size)
    pages = (total + page_size - 1) // page_size if total else 0
    return InviteCodeUsageListOut(
        items=[
            InviteCodeUsageOut(
                id=str(u.id),
                user_email=u.user.email if u.user else None,
                user_name=u.user.name if u.user else None,
                used_at=u.used_at.isoformat(),
            )
            for u in usages
        ],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


# =============================================================================
# Groq API Key Endpoints
# =============================================================================

class GroqKeyStatusOut(BaseModel):
    """Status of the system-wide Groq API key."""
    has_key: bool
    source: str  # "db" | "env" | "none"
    masked_key: Optional[str] = None
    updated_at: Optional[str] = None


class UpdateGroqKeyRequest(BaseModel):
    """Request to set/update the Groq API key."""
    api_key: str = Field(..., min_length=10, max_length=256)


@router.get("/groq-key/status", response_model=GroqKeyStatusOut)
async def get_groq_key_status(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Get the current Groq API key status (has key, source, masked preview)."""
    from backend.services.groq_key_service import (
        get_groq_api_key,
        get_groq_key_record,
        mask_key,
    )
    from backend.core.config import settings

    # Check DB first
    db_key = await get_groq_api_key(db)
    if db_key:
        record = await get_groq_key_record(db)
        updated_at = None
        if record and record.value:
            updated_at = record.value.get("updated_at_iso")
        return GroqKeyStatusOut(
            has_key=True,
            source="db",
            masked_key=mask_key(db_key),
            updated_at=updated_at,
        )

    # Check env var
    env_key = settings.GROQ_API_KEY
    if env_key and env_key.strip():
        return GroqKeyStatusOut(
            has_key=True,
            source="env",
            masked_key=mask_key(env_key),
        )

    return GroqKeyStatusOut(has_key=False, source="none")


@router.put("/groq-key", response_model=MessageOut)
async def update_groq_key(
    body: UpdateGroqKeyRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Validate and store a new Groq API key (encrypted in DB)."""
    from backend.services.groq_key_service import validate_groq_api_key, set_groq_api_key

    # Validate key against Groq API
    valid = await validate_groq_api_key(body.api_key)
    if not valid:
        raise HTTPException(
            status_code=400,
            detail="API key không hợp lệ. Vui lòng kiểm tra lại key từ console.groq.com.",
        )

    await set_groq_api_key(db, body.api_key, updated_by=admin.email)

    logger.info("Admin %s updated Groq API key", admin.email)
    return MessageOut(success=True, message="Đã lưu Groq API key thành công.")


@router.delete("/groq-key", response_model=MessageOut)
async def delete_groq_key(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Remove Groq API key from DB (falls back to env var)."""
    from backend.services.groq_key_service import delete_groq_api_key

    deleted = await delete_groq_api_key(db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Không có Groq API key trong database.")

    logger.info("Admin %s removed Groq API key from DB", admin.email)
    return MessageOut(success=True, message="Đã xoá Groq API key. Hệ thống sẽ dùng biến môi trường nếu có.")


# =============================================================================
# Groq API Key Pool Endpoints
# =============================================================================

class GroqPoolKeyOut(BaseModel):
    id: UUID
    name: str
    enabled: bool
    masked_key: str
    error_count: int
    last_error_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AddGroqPoolKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    api_key: str = Field(..., min_length=10, max_length=256)
    enabled: bool = True


class UpdateGroqPoolKeyRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    api_key: Optional[str] = Field(None, min_length=10, max_length=256)
    enabled: Optional[bool] = None


def _pool_key_to_out(record, plain_key: Optional[str] = None) -> GroqPoolKeyOut:
    from backend.services.groq_key_pool_service import mask_key_value
    from backend.core.security import decrypt_token

    if plain_key is None:
        try:
            plain_key = decrypt_token(record.encrypted_key)
        except Exception:
            plain_key = "***"
    return GroqPoolKeyOut(
        id=record.id,
        name=record.name,
        enabled=record.enabled,
        masked_key=mask_key_value(plain_key),
        error_count=record.error_count,
        last_error_at=record.last_error_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/groq-keys", response_model=List[GroqPoolKeyOut])
async def list_groq_pool_keys(
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """List all Groq API keys in the rotation pool."""
    from backend.services import groq_key_pool_service as pool_svc

    records = await pool_svc.list_keys(db)
    return [_pool_key_to_out(r) for r in records]


@router.post("/groq-keys", response_model=GroqPoolKeyOut, status_code=201)
async def add_groq_pool_key(
    body: AddGroqPoolKeyRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Validate and add a new Groq API key to the pool."""
    from backend.services import groq_key_pool_service as pool_svc

    valid = await pool_svc.validate_plain_key(body.api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="API key không hợp lệ hoặc đã hết hạn.")

    record = await pool_svc.add_key(db, name=body.name, plain_key=body.api_key, enabled=body.enabled)
    logger.info("Admin %s added pool key %s (%s)", admin.email, record.id, body.name)
    return _pool_key_to_out(record, plain_key=body.api_key)


@router.patch("/groq-keys/{key_id}", response_model=GroqPoolKeyOut)
async def update_groq_pool_key(
    key_id: UUID,
    body: UpdateGroqPoolKeyRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update name, key value, or enabled status of a pool key."""
    from backend.services import groq_key_pool_service as pool_svc

    if body.api_key is not None:
        valid = await pool_svc.validate_plain_key(body.api_key)
        if not valid:
            raise HTTPException(status_code=400, detail="API key không hợp lệ hoặc đã hết hạn.")

    record = await pool_svc.update_key(
        db, key_id,
        name=body.name,
        plain_key=body.api_key,
        enabled=body.enabled,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Key không tồn tại.")

    logger.info("Admin %s updated pool key %s", admin.email, key_id)
    return _pool_key_to_out(record)


@router.delete("/groq-keys/{key_id}", response_model=MessageOut)
async def delete_groq_pool_key(
    key_id: UUID,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Remove a key from the pool."""
    from backend.services import groq_key_pool_service as pool_svc

    deleted = await pool_svc.delete_key(db, key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key không tồn tại.")

    logger.info("Admin %s deleted pool key %s", admin.email, key_id)
    return MessageOut(success=True, message="Đã xoá key khỏi pool.")
