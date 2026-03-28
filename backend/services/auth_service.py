"""
Authentication service for user management.
Handles signup, login, and token operations.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import User, CanvasToken, UserRole, UserStatus, TokenType
from backend.core.security import (
    hash_password,
    verify_password,
    dummy_verify_password,
    needs_rehash,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    encrypt_token,
    decrypt_token,
)
from backend.core.exceptions import (
    BadRequestException,
    UnauthorizedException,
    NotFoundException,
)
from backend.core.config import settings
from backend.services.url_safety import validate_canvas_origin_url

logger = logging.getLogger(__name__)


def _mask_email(email: str) -> str:
    """
    Mask an email address for safe logging.
    
    Examples:
        user@example.com -> u***@e***.com
        ab@cd.com -> a***@c***.com
    """
    try:
        local, domain = email.rsplit("@", 1)
        domain_parts = domain.rsplit(".", 1)
        masked_local = local[0] + "***" if local else "***"
        masked_domain = domain_parts[0][0] + "***" if domain_parts[0] else "***"
        tld = domain_parts[1] if len(domain_parts) > 1 else ""
        return f"{masked_local}@{masked_domain}.{tld}"
    except (ValueError, IndexError):
        return "***@***.***"


class AuthService:
    """
    Authentication service with secure password handling and token management.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def signup(
        self,
        email: str,
        name: str,
        password: str,
        canvas_access_token: Optional[str] = None,
        canvas_domain: str = "https://canvas.instructure.com",
        role: UserRole = UserRole.TEACHER,
    ) -> User:
        """
        Create a new user account.
        
        Args:
            email: User email (must be unique)
            name: User display name
            password: Plain text password (will be hashed)
            canvas_access_token: Optional Canvas LMS access token
            canvas_domain: Canvas LMS domain
            role: User role (default: TEACHER)
            
        Returns:
            Created User object
            
        Raises:
            BadRequestException: If email already exists
        """
        # Check for existing user
        existing = await self.get_user_by_email(email)
        if existing:
            logger.warning(f"Signup attempt with existing email: {_mask_email(email)}")
            raise BadRequestException(
                detail="Email already registered",
                error_code="EMAIL_EXISTS"
            )
        
        # Hash password
        password_hash = hash_password(password)
        
        # Create user
        user = User(
            email=email.lower().strip(),
            name=name.strip(),
            password_hash=password_hash,
            role=role,
            status=UserStatus.ACTIVE,
        )
        
        self.db.add(user)
        await self.db.flush()  # Get user.id before creating token
        
        # Create Canvas token if provided
        if canvas_access_token:
            encrypted = encrypt_token(canvas_access_token)
            canvas_token = CanvasToken(
                user_id=user.id,
                canvas_domain=validate_canvas_origin_url(canvas_domain),
                access_token_encrypted=encrypted,
                token_type=TokenType.PAT,
                label="Primary Canvas Account",
            )
            self.db.add(canvas_token)
        
        await self.db.commit()
        await self.db.refresh(user)
        
        logger.info(f"User created: {user.id} ({user.email})")
        return user
    
    async def login(
        self,
        email: str,
        password: str,
    ) -> tuple[User, str, str]:
        """
        Authenticate user and issue tokens.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            Tuple of (User, access_token, refresh_token)
            
        Raises:
            UnauthorizedException: If credentials are invalid
        """
        user = await self.get_user_by_email(email)
        
        if not user:
            # Timing attack prevention: perform a dummy password hash
            # so the response time is the same as a real password check
            dummy_verify_password(password)
            logger.warning(f"Login attempt for non-existent email: {_mask_email(email)}")
            raise UnauthorizedException(
                detail="Invalid email or password",
                error_code="INVALID_CREDENTIALS"
            )
        
        if not user.password_hash:
            # Still do dummy verify to prevent timing leak
            dummy_verify_password(password)
            logger.warning(f"Login attempt for OAuth-only user: {_mask_email(email)}")
            raise UnauthorizedException(
                detail="This account uses OAuth login",
                error_code="OAUTH_ONLY"
            )
        
        if not verify_password(password, user.password_hash):
            logger.warning(f"Invalid password for user: {_mask_email(email)}")
            raise UnauthorizedException(
                detail="Invalid email or password",
                error_code="INVALID_CREDENTIALS"
            )
        
        if not user.is_active:
            logger.warning(f"Login attempt for inactive user: {_mask_email(email)}")
            raise UnauthorizedException(
                detail="Account is disabled",
                error_code="ACCOUNT_DISABLED"
            )
        
        # Check if password needs rehash (algorithm upgrade)
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            logger.info(f"Password rehashed for user: {user.id}")
        
        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        
        # Generate tokens
        access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        refresh_token = create_refresh_token(str(user.id))
        
        logger.info(f"User logged in: {user.id}")
        return user, access_token, refresh_token
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email (case-insensitive)."""
        result = await self.db.execute(
            select(User).where(User.email == email.lower().strip())
        )
        return result.scalar_one_or_none()
    
    async def get_active_canvas_tokens(self, user_id: UUID) -> list[CanvasToken]:
        """Get all active (non-revoked) Canvas tokens for a user."""
        result = await self.db.execute(
            select(CanvasToken)
            .where(CanvasToken.user_id == user_id)
            .where(CanvasToken.revoked_at.is_(None))
            .order_by(CanvasToken.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def get_decrypted_canvas_token(
        self,
        user_id: UUID,
        canvas_domain: Optional[str] = None
    ) -> Optional[str]:
        """
        Get decrypted Canvas access token for a user.
        
        Args:
            user_id: User ID
            canvas_domain: Optional domain filter
            
        Returns:
            Decrypted access token or None
            
        Security Note:
            NEVER log the return value
        """
        query = (
            select(CanvasToken)
            .where(CanvasToken.user_id == user_id)
            .where(CanvasToken.revoked_at.is_(None))
        )
        
        if canvas_domain:
            query = query.where(CanvasToken.canvas_domain == canvas_domain)
        
        query = query.order_by(CanvasToken.created_at.desc()).limit(1)
        
        result = await self.db.execute(query)
        token = result.scalar_one_or_none()
        
        if not token:
            return None
        
        # Update last used timestamp
        token.update_last_used()
        await self.db.commit()
        
        return decrypt_token(token.access_token_encrypted)
    
    async def add_canvas_token(
        self,
        user_id: UUID,
        canvas_domain: str,
        access_token: str,
        token_type: TokenType = TokenType.PAT,
        label: Optional[str] = None,
    ) -> CanvasToken:
        """Add a new Canvas token for a user."""
        encrypted = encrypt_token(access_token)
        
        token = CanvasToken(
            user_id=user_id,
            canvas_domain=validate_canvas_origin_url(canvas_domain),
            access_token_encrypted=encrypted,
            token_type=token_type,
            label=label,
        )
        
        self.db.add(token)
        await self.db.commit()
        await self.db.refresh(token)
        
        logger.info(f"Canvas token added for user: {user_id}")
        return token
    
    async def revoke_canvas_token(self, token_id: UUID, user_id: UUID) -> bool:
        """Revoke a Canvas token (soft delete)."""
        result = await self.db.execute(
            select(CanvasToken)
            .where(CanvasToken.id == token_id)
            .where(CanvasToken.user_id == user_id)
        )
        token = result.scalar_one_or_none()
        
        if not token:
            return False
        
        token.revoke()
        await self.db.commit()
        
        logger.info(f"Canvas token revoked: {token_id}")
        return True
    
    async def refresh_tokens(
        self,
        refresh_token_str: str,
    ) -> tuple[User, str, str]:
        """
        Refresh access token using a valid refresh token.
        
        Issues a new access token and a new refresh token (token rotation).
        The old refresh token is blacklisted to prevent reuse.
        
        Args:
            refresh_token_str: The current refresh token JWT
            
        Returns:
            Tuple of (User, new_access_token, new_refresh_token)
            
        Raises:
            UnauthorizedException: If refresh token is invalid or user not found
        """
        from backend.auth.token_blacklist import blacklist_token, is_token_blacklisted
        
        # Verify the refresh token
        token_data = verify_refresh_token(refresh_token_str)
        if token_data is None:
            raise UnauthorizedException(
                detail="Invalid or expired refresh token",
                error_code="INVALID_REFRESH_TOKEN"
            )
        
        # Check if token is blacklisted
        if token_data.jti and await is_token_blacklisted(token_data.jti):
            logger.warning(f"Attempted use of blacklisted refresh token: user={token_data.user_id}")
            raise UnauthorizedException(
                detail="Refresh token has been revoked",
                error_code="TOKEN_REVOKED"
            )
        
        # Get user
        user = await self.get_user_by_id(UUID(token_data.user_id))
        if user is None:
            raise UnauthorizedException(
                detail="User not found",
                error_code="USER_NOT_FOUND"
            )
        
        if not user.is_active:
            raise UnauthorizedException(
                detail="Account is disabled",
                error_code="ACCOUNT_DISABLED"
            )
        
        # Blacklist the old refresh token (token rotation)
        if token_data.jti:
            await blacklist_token(token_data.jti, token_data.exp)
        
        # Issue new tokens
        new_access_token = create_access_token(
            user_id=str(user.id),
            email=user.email,
            role=user.role.value,
        )
        new_refresh_token = create_refresh_token(str(user.id))
        
        logger.info(f"Tokens refreshed for user: {user.id}")
        return user, new_access_token, new_refresh_token
    
    async def logout(
        self,
        access_token_jti: str,
        access_token_exp: "datetime",
        refresh_token_str: Optional[str] = None,
        logout_all_devices: bool = False,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Logout user by blacklisting their tokens.
        
        Args:
            access_token_jti: JTI of the current access token
            access_token_exp: Expiration of the current access token
            refresh_token_str: Optional refresh token to also revoke
            logout_all_devices: If True, revoke ALL tokens for this user
            user_id: User ID (required for logout_all_devices)
            
        Returns:
            True if successful
        """
        from backend.auth.token_blacklist import (
            blacklist_token,
            blacklist_all_user_tokens,
        )
        
        # Always blacklist the current access token
        await blacklist_token(access_token_jti, access_token_exp)
        
        # Blacklist refresh token if provided
        if refresh_token_str:
            refresh_data = verify_refresh_token(refresh_token_str)
            if refresh_data and refresh_data.jti:
                await blacklist_token(refresh_data.jti, refresh_data.exp)
        
        # Logout from all devices
        if logout_all_devices and user_id:
            await blacklist_all_user_tokens(user_id)
        
        logger.info(f"User logged out: {user_id or 'unknown'}")
        return True
