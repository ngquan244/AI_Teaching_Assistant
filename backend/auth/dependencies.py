"""
FastAPI dependencies for authentication and authorization.
Implements role-based access control (RBAC) with token blacklist support.
"""
import logging
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, User, UserRole
from backend.core.security import verify_access_token, decode_token
from backend.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer token security scheme
security = HTTPBearer(
    scheme_name="JWT",
    description="JWT access token for authentication",
    auto_error=True,
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    Dependency to get the current authenticated user.
    
    Includes token blacklist checking for proper logout support.
    
    Args:
        credentials: Bearer token from Authorization header
        db: Database session
        
    Returns:
        Authenticated User object
        
    Raises:
        HTTPException: 401 if token is invalid, blacklisted, or user not found
    """
    from backend.auth.token_blacklist import (
        is_token_blacklisted,
        is_token_issued_before_revocation,
    )
    
    token = credentials.credentials
    
    # Verify token
    token_data = verify_access_token(token)
    if token_data is None:
        logger.warning("Invalid or expired access token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if token has been blacklisted (logout)
    if token_data.jti and await is_token_blacklisted(token_data.jti):
        logger.warning(f"Blacklisted token used: jti={token_data.jti}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user-level revocation invalidates this token
    if token_data.iat and await is_token_issued_before_revocation(
        token_data.user_id, token_data.iat
    ):
        logger.warning(f"Token issued before user-level revocation: user={token_data.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked (logged out from all devices)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(UUID(token_data.user_id))
    
    if user is None:
        logger.warning(f"User not found for token: {token_data.user_id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        logger.warning(f"Inactive user attempted access: {user.id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    
    return user


async def get_current_user_token_data(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict:
    """
    Dependency to extract token metadata (jti, exp) for logout.
    
    Returns:
        Dict with jti and exp from the current access token
    """
    token = credentials.credentials
    payload = decode_token(token, token_type="access")
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {
        "jti": payload.get("jti", ""),
        "exp": datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
    }


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Dependency to ensure user is active.
    This is a convenience wrapper for get_current_user.
    """
    return current_user


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory for role-based access control.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            user: User = Depends(require_role(UserRole.ADMIN))
        ):
            pass
    
    Args:
        *allowed_roles: Roles allowed to access the endpoint
        
    Returns:
        Dependency function
    """
    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                f"Access denied for user {current_user.id}: "
                f"role {current_user.role} not in {allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user
    
    return role_checker


# Convenience dependencies for common role checks
RequireAdmin = Depends(require_role(UserRole.ADMIN))
RequireTeacher = Depends(require_role(UserRole.TEACHER, UserRole.ADMIN))


# Type aliases for cleaner function signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
ActiveUser = Annotated[User, Depends(get_current_active_user)]
AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
TeacherUser = Annotated[User, Depends(require_role(UserRole.TEACHER, UserRole.ADMIN))]
