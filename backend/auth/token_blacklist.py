"""
Token blacklist service using Redis.
Enables JWT revocation for logout and security purposes.

Blacklisted tokens are stored in Redis with TTL matching the token's
remaining lifetime, so they auto-expire and don't accumulate forever.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Lazy-initialized Redis connection for token blacklist
_redis_client: Optional[aioredis.Redis] = None


async def get_blacklist_redis() -> aioredis.Redis:
    """
    Get or create the Redis connection for token blacklist.
    Uses a dedicated Redis DB to avoid conflicts with Celery.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.TOKEN_BLACKLIST_REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


def _blacklist_key(jti: str) -> str:
    """Generate Redis key for a blacklisted token."""
    return f"token_blacklist:{jti}"


async def blacklist_token(jti: str, exp: datetime) -> bool:
    """
    Add a token to the blacklist.
    
    The token is stored with a TTL equal to its remaining lifetime,
    so it auto-expires from Redis when the JWT would have expired anyway.
    
    Args:
        jti: Unique token identifier (JWT ID)
        exp: Token expiration datetime (UTC)
        
    Returns:
        True if successfully blacklisted
    """
    try:
        redis_client = await get_blacklist_redis()
        
        # Calculate remaining TTL
        now = datetime.now(timezone.utc)
        remaining_seconds = int((exp - now).total_seconds())
        
        if remaining_seconds <= 0:
            # Token already expired, no need to blacklist
            return True
        
        # Store with TTL so it auto-expires
        key = _blacklist_key(jti)
        await redis_client.setex(key, remaining_seconds, "revoked")
        
        logger.debug(f"Token blacklisted: jti={jti}, ttl={remaining_seconds}s")
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist token: {type(e).__name__}: {e}")
        return False


async def is_token_blacklisted(jti: str) -> bool:
    """
    Check if a token has been blacklisted (revoked).
    
    Args:
        jti: Unique token identifier (JWT ID)
        
    Returns:
        True if the token is blacklisted
    """
    try:
        redis_client = await get_blacklist_redis()
        key = _blacklist_key(jti)
        result = await redis_client.exists(key)
        return bool(result)
    except Exception as e:
        # If Redis is down, fail-open for availability
        # In high-security environments, change to fail-closed
        logger.error(f"Failed to check token blacklist: {type(e).__name__}: {e}")
        return False


async def blacklist_all_user_tokens(user_id: str) -> bool:
    """
    Blacklist all tokens for a user (force logout everywhere).
    
    This stores a user-level revocation timestamp. Any token issued
    before this timestamp is considered revoked.
    
    Args:
        user_id: User UUID as string
        
    Returns:
        True if successfully stored
    """
    try:
        redis_client = await get_blacklist_redis()
        key = f"user_token_revoked_at:{user_id}"
        now = datetime.now(timezone.utc).timestamp()
        
        # Keep for the max possible token lifetime (refresh token days)
        ttl = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
        await redis_client.setex(key, ttl, str(now))
        
        logger.info(f"All tokens revoked for user: {user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke all user tokens: {type(e).__name__}: {e}")
        return False


async def is_token_issued_before_revocation(user_id: str, iat: float) -> bool:
    """
    Check if a token was issued before a user-level revocation.
    
    Args:
        user_id: User UUID as string
        iat: Token issued-at timestamp (epoch)
        
    Returns:
        True if the token was issued before revocation (should be rejected)
    """
    try:
        redis_client = await get_blacklist_redis()
        key = f"user_token_revoked_at:{user_id}"
        revoked_at = await redis_client.get(key)
        
        if revoked_at is None:
            return False
        
        return iat < float(revoked_at)
    except Exception as e:
        logger.error(f"Failed to check user token revocation: {type(e).__name__}: {e}")
        return False


async def close_blacklist_connection() -> None:
    """Close the Redis connection gracefully."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
