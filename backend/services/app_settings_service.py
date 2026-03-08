"""
App Settings Service — runtime configuration from DB.

Provides a thin caching layer over the `app_settings` table so that
every request doesn't hit the DB.  Cache TTL = 60 s by default.
"""
import time
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.database.models.invite_code import AppSetting

settings = get_settings()

# ─── In-memory cache ─────────────────────────────────────────────────────────
_CACHE_TTL: int = 60  # seconds
_cache: Dict[str, tuple[Any, float]] = {}  # key -> (value, fetched_at)


def _get_cached(key: str) -> Optional[Any]:
    """Return cached value if still fresh, else None."""
    entry = _cache.get(key)
    if entry is None:
        return None
    value, fetched_at = entry
    if time.monotonic() - fetched_at > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _set_cached(key: str, value: Any) -> None:
    _cache[key] = (value, time.monotonic())


def invalidate_cache(key: Optional[str] = None) -> None:
    """Clear a single key or the entire cache."""
    if key is None:
        _cache.clear()
    else:
        _cache.pop(key, None)


# ─── DB operations ───────────────────────────────────────────────────────────

async def get_setting(db: AsyncSession, key: str) -> Optional[Any]:
    """
    Get a setting value from DB (with in-memory cache).
    Returns the unwrapped JSON value, or None if not set.
    """
    cached = _get_cached(key)
    if cached is not None:
        return cached

    row = await db.get(AppSetting, key)
    if row is None:
        return None

    _set_cached(key, row.value)
    return row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> AppSetting:
    """
    Upsert a setting value.  Invalidates cache immediately.
    """
    row = await db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value

    await db.flush()
    invalidate_cache(key)
    return row


# ─── Convenience helpers ─────────────────────────────────────────────────────

async def get_signup_mode(db: AsyncSession) -> str:
    """
    Return the effective signup mode.
    Priority: DB app_settings > env var fallback.
    """
    db_mode = await get_setting(db, "SIGNUP_MODE")
    if db_mode and isinstance(db_mode, str) and db_mode in {"open", "invite", "closed"}:
        return db_mode
    # Fallback to env var
    return settings.SIGNUP_MODE
