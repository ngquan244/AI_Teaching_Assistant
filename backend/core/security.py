"""
Security utilities for authentication and encryption.
Implements industry best practices for password hashing and token encryption.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import base64
import logging

from cryptography.fernet import Fernet
from passlib.context import CryptContext
from jose import jwt, JWTError

from backend.core.config import settings

# Configure logger - NEVER log sensitive data
logger = logging.getLogger(__name__)


# =============================================================================
# Password Hashing
# =============================================================================

# Password context supporting both argon2 and bcrypt
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    default=settings.PASSWORD_HASH_ALGORITHM,
    deprecated="auto",
    # Argon2 parameters (secure defaults)
    argon2__memory_cost=65536,  # 64 MB
    argon2__time_cost=3,
    argon2__parallelism=4,
    # Bcrypt parameters
    bcrypt__rounds=settings.BCRYPT_ROUNDS,
)

# Pre-computed dummy hash for timing attack prevention.
# Used when a login attempt targets a non-existent email so that
# the response time is indistinguishable from a real password check.
_DUMMY_HASH = pwd_context.hash("timing-attack-prevention-dummy-password")


def hash_password(password: str) -> str:
    """
    Hash a password using argon2 or bcrypt.
    
    Args:
        password: Plain text password
        
    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.
    
    Args:
        plain_password: Plain text password to verify
        hashed_password: Stored password hash
        
    Returns:
        True if password matches, False otherwise
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.warning(f"Password verification error: {type(e).__name__}")
        return False


def dummy_verify_password(plain_password: str) -> None:
    """
    Perform a dummy password verification to prevent timing attacks.
    
    When a login attempt uses a non-existent email, calling this ensures
    the response time is similar to a real password verification,
    making it impossible to enumerate valid emails via timing analysis.
    
    Args:
        plain_password: The password to verify against the dummy hash
    """
    try:
        pwd_context.verify(plain_password, _DUMMY_HASH)
    except Exception:
        pass


def needs_rehash(hashed_password: str) -> bool:
    """
    Check if password hash needs to be upgraded to a stronger algorithm.
    
    Args:
        hashed_password: Current password hash
        
    Returns:
        True if rehash is recommended
    """
    return pwd_context.needs_update(hashed_password)


# =============================================================================
# JWT Token Management
# =============================================================================

class TokenData:
    """Container for decoded JWT token data."""
    def __init__(
        self,
        user_id: str,
        email: str,
        role: str,
        exp: datetime,
        token_type: str = "access",
        jti: Optional[str] = None,
        iat: Optional[float] = None,
    ):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.exp = exp
        self.token_type = token_type
        self.jti = jti
        self.iat = iat


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.
    
    Args:
        user_id: User UUID as string
        email: User email
        role: User role (ADMIN/TEACHER)
        expires_delta: Custom expiration time
        
    Returns:
        Encoded JWT token string
    """
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": secrets.token_urlsafe(16),  # Unique token ID
    }
    
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def create_refresh_token(user_id: str) -> str:
    """
    Create a JWT refresh token (longer-lived, minimal claims).
    Uses a SEPARATE secret key from access tokens for defense in depth.
    
    Args:
        user_id: User UUID as string
        
    Returns:
        Encoded JWT refresh token
    """
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": secrets.token_urlsafe(16),
    }
    
    return jwt.encode(
        payload,
        settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )


def decode_token(token: str, token_type: str = "access") -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        token_type: "access" or "refresh" — determines which secret key to use
        
    Returns:
        Decoded payload dict or None if invalid
    """
    secret_key = (
        settings.JWT_REFRESH_SECRET_KEY
        if token_type == "refresh"
        else settings.JWT_SECRET_KEY
    )
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        logger.warning(f"JWT decode error: {type(e).__name__}")
        return None


def verify_access_token(token: str) -> Optional[TokenData]:
    """
    Verify an access token and return token data.
    
    Args:
        token: JWT access token
        
    Returns:
        TokenData if valid, None otherwise
    """
    payload = decode_token(token, token_type="access")
    if payload is None:
        return None
    
    if payload.get("type") != "access":
        logger.warning("Token type mismatch: expected 'access'")
        return None
    
    try:
        return TokenData(
            user_id=payload["sub"],
            email=payload["email"],
            role=payload["role"],
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            token_type="access",
            jti=payload.get("jti"),
            iat=payload.get("iat"),
        )
    except KeyError as e:
        logger.warning(f"Missing token claim: {e}")
        return None


def verify_refresh_token(token: str) -> Optional[TokenData]:
    """
    Verify a refresh token and return token data.
    Uses the separate refresh secret key.
    
    Args:
        token: JWT refresh token
        
    Returns:
        TokenData if valid, None otherwise
    """
    payload = decode_token(token, token_type="refresh")
    if payload is None:
        return None
    
    if payload.get("type") != "refresh":
        logger.warning("Token type mismatch: expected 'refresh'")
        return None
    
    try:
        return TokenData(
            user_id=payload["sub"],
            email="",  # Refresh tokens don't carry email
            role="",   # Refresh tokens don't carry role
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            token_type="refresh",
            jti=payload.get("jti"),
            iat=payload.get("iat"),
        )
    except KeyError as e:
        logger.warning(f"Missing refresh token claim: {e}")
        return None


# =============================================================================
# Canvas Token Encryption (AES-256 via Fernet)
# =============================================================================

def get_fernet() -> Fernet:
    """
    Get Fernet cipher instance for encryption/decryption.
    
    Fernet requires a 32-byte URL-safe base64-encoded key.
    This function handles two common key formats:
    1. A raw 32-byte key (will be base64-encoded)
    2. A proper 44-char base64-encoded Fernet key
    """
    key = settings.ENCRYPTION_KEY
    
    # Case 1: Raw 32-byte key — encode to base64 for Fernet
    if len(key) == 32 and not key.endswith("="):
        key = base64.urlsafe_b64encode(key.encode()).decode()
    # Case 2: Already a valid Fernet key (44 chars, base64-encoded)
    elif len(key) == 44 and key.endswith("="):
        pass  # Already valid
    else:
        # Try to use as-is; Fernet will raise if invalid
        logger.warning(
            f"ENCRYPTION_KEY has unexpected length ({len(key)}). "
            "Expected 32 raw bytes or 44-char base64 Fernet key."
        )
    
    return Fernet(key.encode())


def encrypt_token(plain_token: str) -> str:
    """
    Encrypt a Canvas access token for secure storage.
    
    Args:
        plain_token: Plain text Canvas access token
        
    Returns:
        Base64-encoded encrypted token
        
    Security Note:
        - Uses Fernet (AES-128-CBC with HMAC)
        - Includes timestamp for optional rotation
        - NEVER log the plain_token value
    """
    fernet = get_fernet()
    encrypted = fernet.encrypt(plain_token.encode())
    return encrypted.decode()


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt a stored Canvas access token.
    
    Args:
        encrypted_token: Base64-encoded encrypted token
        
    Returns:
        Plain text Canvas access token
        
    Security Note:
        - NEVER log the return value
        - Handle decryption errors gracefully
    """
    fernet = get_fernet()
    decrypted = fernet.decrypt(encrypted_token.encode())
    return decrypted.decode()


# =============================================================================
# Utility Functions
# =============================================================================

def generate_secret_key(length: int = 32) -> str:
    """
    Generate a cryptographically secure secret key.
    
    Args:
        length: Key length in bytes
        
    Returns:
        URL-safe base64-encoded key
    """
    return secrets.token_urlsafe(length)


def generate_fernet_key() -> str:
    """
    Generate a valid Fernet encryption key.
    
    Returns:
        Base64-encoded 32-byte key suitable for Fernet
    """
    return Fernet.generate_key().decode()
