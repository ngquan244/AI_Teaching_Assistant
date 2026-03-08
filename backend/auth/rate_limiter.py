"""
Login rate limiter using Redis sliding window.
Protects against brute-force password attacks.

Strategy:
- Track failed login attempts per IP address AND per email
- After N failures in a time window, temporarily lock out
- Successful login resets the counter
- Uses Redis for distributed rate limiting (works across multiple workers)
"""
import logging
from typing import Optional

import redis.asyncio as aioredis

from backend.core.config import settings

logger = logging.getLogger(__name__)

# Reuse the same Redis connection from token_blacklist
_redis_client: Optional[aioredis.Redis] = None


async def _get_redis() -> aioredis.Redis:
    """Get or create the Redis connection for rate limiting."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD,
            db=settings.TOKEN_BLACKLIST_REDIS_DB,  # Share DB with blacklist
            decode_responses=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


def _ip_key(ip: str) -> str:
    """Redis key for IP-based rate limiting."""
    return f"login_rate:ip:{ip}"


def _email_key(email: str) -> str:
    """Redis key for email-based rate limiting."""
    return f"login_rate:email:{email.lower().strip()}"


def _lockout_ip_key(ip: str) -> str:
    """Redis key for IP lockout."""
    return f"login_lockout:ip:{ip}"


def _lockout_email_key(email: str) -> str:
    """Redis key for email lockout."""
    return f"login_lockout:email:{email.lower().strip()}"


# ── Signup rate limiting keys ────────────────────────────────────────────────

def _signup_ip_key(ip: str) -> str:
    """Redis key for signup IP-based rate limiting."""
    return f"signup_rate:ip:{ip}"


def _signup_lockout_ip_key(ip: str) -> str:
    """Redis key for signup IP lockout."""
    return f"signup_lockout:ip:{ip}"


async def is_login_locked_out(ip: str, email: str) -> tuple[bool, int]:
    """
    Check if login is currently locked out for this IP or email.
    
    Args:
        ip: Client IP address
        email: Login email address
        
    Returns:
        Tuple of (is_locked_out, remaining_seconds)
    """
    try:
        redis_client = await _get_redis()
        
        # Check both IP and email lockouts
        ip_ttl = await redis_client.ttl(_lockout_ip_key(ip))
        email_ttl = await redis_client.ttl(_lockout_email_key(email))
        
        # ttl returns -2 if key doesn't exist, -1 if no expiry
        max_ttl = max(ip_ttl, email_ttl)
        
        if max_ttl > 0:
            return True, max_ttl
        
        return False, 0
    except Exception as e:
        logger.error(f"Rate limiter check failed: {type(e).__name__}: {e}")
        # Fail-open: don't block login if Redis is down
        return False, 0


async def record_failed_login(ip: str, email: str) -> tuple[bool, int]:
    """
    Record a failed login attempt and check if lockout should be triggered.
    
    Args:
        ip: Client IP address
        email: Login email address
        
    Returns:
        Tuple of (is_now_locked_out, remaining_attempts)
    """
    try:
        redis_client = await _get_redis()
        max_attempts = settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS
        window = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        lockout_duration = settings.LOGIN_LOCKOUT_DURATION_SECONDS
        
        # Increment attempt counters
        ip_key = _ip_key(ip)
        email_key = _email_key(email)
        
        pipe = redis_client.pipeline()
        pipe.incr(ip_key)
        pipe.expire(ip_key, window)
        pipe.incr(email_key)
        pipe.expire(email_key, window)
        results = await pipe.execute()
        
        ip_attempts = results[0]
        email_attempts = results[2]
        
        # Check if either exceeds the limit
        if ip_attempts >= max_attempts or email_attempts >= max_attempts:
            # Set lockout
            pipe2 = redis_client.pipeline()
            pipe2.setex(_lockout_ip_key(ip), lockout_duration, "locked")
            pipe2.setex(_lockout_email_key(email), lockout_duration, "locked")
            await pipe2.execute()
            
            logger.warning(
                f"Login lockout triggered: ip_attempts={ip_attempts}, "
                f"email_attempts={email_attempts}, lockout={lockout_duration}s"
            )
            return True, 0
        
        remaining = max_attempts - max(ip_attempts, email_attempts)
        return False, remaining
    except Exception as e:
        logger.error(f"Rate limiter record failed: {type(e).__name__}: {e}")
        return False, settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


async def reset_login_attempts(ip: str, email: str) -> None:
    """
    Reset login attempt counters after a successful login.
    
    Args:
        ip: Client IP address
        email: Login email address
    """
    try:
        redis_client = await _get_redis()
        
        pipe = redis_client.pipeline()
        pipe.delete(_ip_key(ip))
        pipe.delete(_email_key(email))
        pipe.delete(_lockout_ip_key(ip))
        pipe.delete(_lockout_email_key(email))
        await pipe.execute()
    except Exception as e:
        logger.error(f"Rate limiter reset failed: {type(e).__name__}: {e}")


async def get_remaining_attempts(ip: str, email: str) -> int:
    """
    Get the number of remaining login attempts.
    
    Args:
        ip: Client IP address
        email: Login email address
        
    Returns:
        Number of remaining attempts
    """
    try:
        redis_client = await _get_redis()
        max_attempts = settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS
        
        ip_attempts = await redis_client.get(_ip_key(ip))
        email_attempts = await redis_client.get(_email_key(email))
        
        current = max(
            int(ip_attempts) if ip_attempts else 0,
            int(email_attempts) if email_attempts else 0,
        )
        
        return max(0, max_attempts - current)
    except Exception as e:
        logger.error(f"Rate limiter query failed: {type(e).__name__}: {e}")
        return settings.LOGIN_RATE_LIMIT_MAX_ATTEMPTS


# =============================================================================
# Signup Rate Limiting
# =============================================================================

async def is_signup_locked_out(ip: str) -> tuple[bool, int]:
    """
    Check if signup is currently locked out for this IP.

    Returns:
        Tuple of (is_locked_out, remaining_seconds)
    """
    try:
        redis_client = await _get_redis()
        ttl = await redis_client.ttl(_signup_lockout_ip_key(ip))
        if ttl > 0:
            return True, ttl
        return False, 0
    except Exception as e:
        logger.error(f"Signup rate limiter check failed: {type(e).__name__}: {e}")
        return False, 0


async def record_failed_signup(ip: str) -> tuple[bool, int]:
    """
    Record a failed/attempted signup and check if lockout should be triggered.

    Returns:
        Tuple of (is_now_locked_out, remaining_attempts)
    """
    try:
        redis_client = await _get_redis()
        max_attempts = settings.SIGNUP_RATE_LIMIT_MAX_ATTEMPTS
        window = settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS
        lockout_duration = settings.SIGNUP_LOCKOUT_DURATION_SECONDS

        key = _signup_ip_key(ip)
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        results = await pipe.execute()

        attempts = results[0]

        if attempts >= max_attempts:
            await redis_client.setex(
                _signup_lockout_ip_key(ip), lockout_duration, "locked"
            )
            logger.warning(
                f"Signup lockout triggered for IP: attempts={attempts}, "
                f"lockout={lockout_duration}s"
            )
            return True, 0

        return False, max_attempts - attempts
    except Exception as e:
        logger.error(f"Signup rate limiter record failed: {type(e).__name__}: {e}")
        return False, settings.SIGNUP_RATE_LIMIT_MAX_ATTEMPTS


async def reset_signup_attempts(ip: str) -> None:
    """Reset signup attempt counters after a successful signup."""
    try:
        redis_client = await _get_redis()
        pipe = redis_client.pipeline()
        pipe.delete(_signup_ip_key(ip))
        pipe.delete(_signup_lockout_ip_key(ip))
        await pipe.execute()
    except Exception as e:
        logger.error(f"Signup rate limiter reset failed: {type(e).__name__}: {e}")
