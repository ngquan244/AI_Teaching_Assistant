"""
Authentication API routes.
Handles signup, login, logout, token refresh, and user profile endpoints.
"""
import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.auth_service import AuthService
from backend.core.config import settings
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    verify_access_token,
)
from backend.auth.schemas import (
    SignupRequest,
    SignupResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    MessageResponse,
    UserResponse,
    UserProfileResponse,
    AuthTokenResponse,
    CanvasTokenResponse,
    AddCanvasTokenRequest,
    DecryptedCanvasTokenResponse,
)
from backend.auth.dependencies import CurrentUser, get_current_user_token_data
from backend.auth.rate_limiter import (
    is_login_locked_out,
    record_failed_login,
    reset_login_attempts,
)
from backend.core.exceptions import UnauthorizedException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
    description="Create a new user account with email/password authentication. "
                "Optionally provide a Canvas LMS access token.",
)
async def signup(
    request: SignupRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SignupResponse:
    """
    Register a new user account.
    
    - **email**: User email (must be unique)
    - **name**: User display name
    - **password**: Password (min 8 chars, must include uppercase, lowercase, digit, special char)
    - **canvas_access_token**: Optional Canvas LMS access token
    - **canvas_domain**: Canvas LMS domain (default: canvas.instructure.com)
    """
    auth_service = AuthService(db)
    
    user = await auth_service.signup(
        email=request.email,
        name=request.name,
        password=request.password,
        canvas_access_token=request.canvas_access_token,
        canvas_domain=request.canvas_domain,
    )
    
    # Generate tokens directly (no need to call login again)
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role.value,
    )
    refresh_token = create_refresh_token(str(user.id))
    
    return SignupResponse(
        user=UserResponse.model_validate(user),
        tokens=AuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
        message="Account created successfully",
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Authenticate user",
    description="Authenticate with email and password. Returns JWT tokens. "
                "Rate-limited to prevent brute-force attacks.",
)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
    """
    Authenticate user and issue JWT tokens.
    
    - **email**: User email address
    - **password**: User password
    
    Rate limiting: Max 5 attempts per 5-minute window per IP/email.
    Lockout: 15 minutes after exceeding the limit.
    """
    # Extract client IP for rate limiting
    client_ip = http_request.client.host if http_request.client else "unknown"
    
    # Check if locked out
    locked_out, remaining_seconds = await is_login_locked_out(client_ip, request.email)
    if locked_out:
        logger.warning(f"Login locked out for IP={client_ip}, remaining={remaining_seconds}s")
        raise UnauthorizedException(
            detail=f"Too many login attempts. Please try again in {remaining_seconds // 60 + 1} minutes.",
            error_code="LOGIN_RATE_LIMITED"
        )
    
    auth_service = AuthService(db)
    
    try:
        user, access_token, refresh_token = await auth_service.login(
            email=request.email,
            password=request.password,
        )
    except UnauthorizedException:
        # Record failed attempt for rate limiting
        is_locked, attempts_remaining = await record_failed_login(client_ip, request.email)
        if is_locked:
            raise UnauthorizedException(
                detail=f"Too many login attempts. Account temporarily locked for "
                       f"{settings.LOGIN_LOCKOUT_DURATION_SECONDS // 60} minutes.",
                error_code="LOGIN_RATE_LIMITED"
            )
        raise  # Re-raise original exception
    
    # Success: reset rate limit counters
    await reset_login_attempts(client_ip, request.email)
    
    return LoginResponse(
        user=UserResponse.model_validate(user),
        tokens=AuthTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
    )


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    summary="Refresh access token",
    description="Exchange a valid refresh token for a new access token. "
                "The old refresh token is revoked (token rotation).",
)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RefreshTokenResponse:
    """
    Refresh the access token using a valid refresh token.
    
    Implements token rotation: each refresh issues a new refresh token
    and invalidates the old one, limiting the impact of token theft.
    
    - **refresh_token**: Current valid refresh token
    """
    auth_service = AuthService(db)
    
    user, new_access_token, new_refresh_token = await auth_service.refresh_tokens(
        refresh_token_str=request.refresh_token,
    )
    
    return RefreshTokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout user",
    description="Revoke the current access token and optionally the refresh token. "
                "Supports logout from all devices.",
)
async def logout(
    request: LogoutRequest,
    current_user: CurrentUser,
    token_data: Annotated[dict, Depends(get_current_user_token_data)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """
    Logout the current user.
    
    - **refresh_token**: Optional refresh token to also revoke
    - **logout_all_devices**: If true, invalidate ALL tokens for this user
    """
    auth_service = AuthService(db)
    
    await auth_service.logout(
        access_token_jti=token_data["jti"],
        access_token_exp=token_data["exp"],
        refresh_token_str=request.refresh_token,
        logout_all_devices=request.logout_all_devices,
        user_id=str(current_user.id),
    )
    
    message = (
        "Logged out from all devices successfully"
        if request.logout_all_devices
        else "Logged out successfully"
    )
    return MessageResponse(message=message)


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Get current user profile",
    description="Get the authenticated user's profile with Canvas tokens.",
)
async def get_current_user_profile(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
    """
    Get the current user's profile including Canvas tokens.
    
    Requires valid JWT access token in Authorization header.
    """
    auth_service = AuthService(db)
    
    # Get Canvas tokens
    canvas_tokens = await auth_service.get_active_canvas_tokens(current_user.id)
    
    return UserProfileResponse(
        user=UserResponse.model_validate(current_user),
        canvas_tokens=[
            CanvasTokenResponse(
                id=token.id,
                canvas_domain=token.canvas_domain,
                token_type=token.token_type,
                label=token.label,
                created_at=token.created_at,
                last_used_at=token.last_used_at,
                is_active=token.is_active,
            )
            for token in canvas_tokens
        ],
    )


@router.post(
    "/canvas-tokens",
    response_model=CanvasTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Canvas LMS token",
    description="Add a new Canvas LMS access token for the current user.",
)
async def add_canvas_token(
    request: AddCanvasTokenRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CanvasTokenResponse:
    """
    Add a Canvas LMS access token.
    
    - **canvas_domain**: Canvas LMS domain URL
    - **access_token**: Canvas access token (will be encrypted)
    - **token_type**: PAT or OAUTH
    - **label**: Optional friendly label
    """
    auth_service = AuthService(db)
    
    token = await auth_service.add_canvas_token(
        user_id=current_user.id,
        canvas_domain=request.canvas_domain,
        access_token=request.access_token,
        token_type=request.token_type,
        label=request.label,
    )
    
    return CanvasTokenResponse(
        id=token.id,
        canvas_domain=token.canvas_domain,
        token_type=token.token_type,
        label=token.label,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active,
    )


@router.delete(
    "/canvas-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke Canvas token",
    description="Revoke (soft delete) a Canvas LMS access token.",
)
async def revoke_canvas_token(
    token_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Revoke a Canvas LMS access token."""
    from uuid import UUID
    from backend.core.exceptions import NotFoundException
    
    auth_service = AuthService(db)
    
    success = await auth_service.revoke_canvas_token(
        token_id=UUID(token_id),
        user_id=current_user.id,
    )
    
    if not success:
        raise NotFoundException(
            detail="Canvas token not found",
            error_code="TOKEN_NOT_FOUND",
        )


@router.get(
    "/canvas-tokens/active",
    response_model=DecryptedCanvasTokenResponse,
    summary="Get active Canvas token (decrypted)",
    description="Get the most recently used active Canvas token for API calls.",
)
async def get_active_canvas_token(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    canvas_domain: Optional[str] = None,
) -> DecryptedCanvasTokenResponse:
    """
    Get decrypted Canvas access token for API calls.
    
    Query params:
        canvas_domain: Optional filter by domain
    """
    from backend.core.exceptions import NotFoundException
    
    auth_service = AuthService(db)
    
    # Get active tokens to find the domain
    tokens = await auth_service.get_active_canvas_tokens(current_user.id)
    
    if not tokens:
        raise NotFoundException(
            detail="No active Canvas token found",
            error_code="NO_CANVAS_TOKEN",
        )
    
    # Use provided domain or get from first token
    domain = canvas_domain or tokens[0].canvas_domain
    
    decrypted = await auth_service.get_decrypted_canvas_token(
        user_id=current_user.id,
        canvas_domain=domain if canvas_domain else None,
    )
    
    if not decrypted:
        raise NotFoundException(
            detail="Canvas token not found or could not be decrypted",
            error_code="TOKEN_DECRYPT_FAILED",
        )
    
    return DecryptedCanvasTokenResponse(
        access_token=decrypted,
        canvas_domain=domain,
    )
