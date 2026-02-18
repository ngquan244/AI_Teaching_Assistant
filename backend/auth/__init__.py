# Authentication package
from .dependencies import (
    get_current_user,
    get_current_active_user,
    get_current_user_token_data,
    require_role,
    CurrentUser,
    ActiveUser,
    AdminUser,
    TeacherUser,
)
from .routes import router as auth_router
from .schemas import (
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
)

__all__ = [
    # Dependencies
    "get_current_user",
    "get_current_active_user",
    "get_current_user_token_data",
    "require_role",
    "CurrentUser",
    "ActiveUser",
    "AdminUser",
    "TeacherUser",
    # Router
    "auth_router",
    # Schemas
    "SignupRequest",
    "SignupResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutRequest",
    "RefreshTokenRequest",
    "RefreshTokenResponse",
    "MessageResponse",
    "UserResponse",
    "UserProfileResponse",
    "AuthTokenResponse",
    "CanvasTokenResponse",
]
