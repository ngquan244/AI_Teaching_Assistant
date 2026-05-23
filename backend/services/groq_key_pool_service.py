"""
Groq API Key Pool Service
==========================
CRUD and round-robin selection for the ``groq_api_keys`` table.

Async helpers are used by FastAPI admin routes.
A lightweight **sync** helper (``get_pool_keys_sync``) is provided for the
Celery worker which cannot use ``await``.
"""
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.core.security import encrypt_token, decrypt_token
from backend.database.models.groq_api_key import GroqApiKey

logger = logging.getLogger(__name__)

_GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# ---------------------------------------------------------------------------
# Async helpers (FastAPI)
# ---------------------------------------------------------------------------


async def list_keys(db: AsyncSession) -> List[GroqApiKey]:
    """Return all pool keys ordered by creation time."""
    stmt = select(GroqApiKey).order_by(GroqApiKey.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_key_by_id(db: AsyncSession, key_id: _uuid.UUID) -> Optional[GroqApiKey]:
    stmt = select(GroqApiKey).where(GroqApiKey.id == key_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def add_key(
    db: AsyncSession,
    *,
    name: str,
    plain_key: str,
    enabled: bool = True,
) -> GroqApiKey:
    """Encrypt *plain_key* and persist a new pool entry."""
    record = GroqApiKey(
        name=name,
        encrypted_key=encrypt_token(plain_key),
        enabled=enabled,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    logger.info("Added Groq pool key %s (%s)", record.id, name)
    return record


async def update_key(
    db: AsyncSession,
    key_id: _uuid.UUID,
    *,
    name: Optional[str] = None,
    plain_key: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> Optional[GroqApiKey]:
    """Update fields on an existing pool key. Returns None if not found."""
    record = await get_key_by_id(db, key_id)
    if record is None:
        return None
    if name is not None:
        record.name = name
    if plain_key is not None:
        record.encrypted_key = encrypt_token(plain_key)
    if enabled is not None:
        record.enabled = enabled
    record.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    logger.info("Updated Groq pool key %s", key_id)
    return record


async def delete_key(db: AsyncSession, key_id: _uuid.UUID) -> bool:
    """Delete a pool key. Returns True if removed."""
    record = await get_key_by_id(db, key_id)
    if record is None:
        return False
    await db.delete(record)
    await db.commit()
    logger.info("Deleted Groq pool key %s", key_id)
    return True


async def validate_plain_key(plain_key: str) -> bool:
    """Quick probe against the Groq models endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _GROQ_MODELS_URL,
                headers={"Authorization": f"Bearer {plain_key}"},
            )
        return resp.status_code == 200
    except Exception:
        logger.warning("Groq pool key validation failed (network error)")
        return False


def mask_key_value(plain_key: str) -> str:
    if len(plain_key) <= 8:
        return "***"
    return f"{plain_key[:6]}...{plain_key[-4:]}"


# ---------------------------------------------------------------------------
# Sync helpers (Celery worker)
# ---------------------------------------------------------------------------

def get_pool_keys_sync(db: Session) -> List[Dict]:
    """
    Fetch all *enabled* pool keys from DB (sync), decrypt them, and return
    lightweight dicts suitable for the key-rotation logic in the quiz
    generator.

    Returns a list ordered by ``last_used_at NULLS FIRST`` (least-recently
    used first) so the caller can simply pop from the front.

    Each dict: ``{id, name, plain_key, error_count, last_error_at}``
    """
    stmt = (
        select(GroqApiKey)
        .where(GroqApiKey.enabled.is_(True))
        .order_by(GroqApiKey.last_used_at.asc().nulls_first())
    )
    rows = db.execute(stmt).scalars().all()
    keys: List[Dict] = []
    for row in rows:
        try:
            plain = decrypt_token(row.encrypted_key)
        except Exception:
            logger.warning("Cannot decrypt pool key %s – skipping", row.id)
            continue
        keys.append({
            "id": row.id,
            "name": row.name,
            "plain_key": plain,
            "masked_key": mask_key_value(plain),
            "error_count": row.error_count,
            "last_error_at": row.last_error_at,
        })
    return keys


def record_key_success_sync(db: Session, key_id: _uuid.UUID) -> None:
    """Mark a successful use: reset error_count, bump last_used_at."""
    stmt = (
        update(GroqApiKey)
        .where(GroqApiKey.id == key_id)
        .values(
            error_count=0,
            last_used_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.execute(stmt)
    db.commit()


def record_key_error_sync(db: Session, key_id: _uuid.UUID) -> None:
    """Increment error_count and set last_error_at."""
    stmt = (
        update(GroqApiKey)
        .where(GroqApiKey.id == key_id)
        .values(
            error_count=GroqApiKey.error_count + 1,
            last_error_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.execute(stmt)
    db.commit()


# ---------------------------------------------------------------------------
# Pool rotation helper (used inside the quiz generator / llm_tasks)
# ---------------------------------------------------------------------------

# Max consecutive errors before a key is auto-skipped within a single quiz run
_MAX_ERRORS_BEFORE_SKIP = 3


class KeyPool:
    """
    Lightweight in-memory key rotator initialised from a list of dicts
    returned by ``get_pool_keys_sync``.

    Usage inside a quiz generation run::

        pool = KeyPool(get_pool_keys_sync(db))
        key_info = pool.next_key()   # round-robin, skip errored
        ...on API error...
        pool.mark_error(key_info["id"])
        key_info = pool.next_key()   # tries next key
    """

    def __init__(self, keys: List[Dict]) -> None:
        self._keys = list(keys)
        self._index = 0
        # Track errors within this run (not persisted until flush)
        self._run_errors: Dict[_uuid.UUID, int] = {}
        # Last key id returned by next_key(); used purely for KEY_SWITCH logging
        self._last_returned_id: Optional[_uuid.UUID] = None

    @property
    def size(self) -> int:
        return len(self._keys)

    def next_key(self) -> Optional[Dict]:
        """Return the next usable key, or ``None`` if all keys exhausted."""
        if not self._keys:
            return None
        tried = 0
        while tried < len(self._keys):
            candidate = self._keys[self._index % len(self._keys)]
            self._index += 1
            tried += 1
            run_err = self._run_errors.get(candidate["id"], 0)
            if run_err >= _MAX_ERRORS_BEFORE_SKIP:
                continue
            # Emit KEY_SWITCH whenever the returned key changes (or first selection).
            if self._last_returned_id != candidate["id"]:
                logger.info(
                    "KEY_SWITCH from_key_id=%s to_key_id=%s to_masked=%s pool_size=%d",
                    str(self._last_returned_id) if self._last_returned_id else "-",
                    str(candidate["id"]),
                    candidate.get("masked_key", "?"),
                    len(self._keys),
                )
            self._last_returned_id = candidate["id"]
            return candidate
        logger.warning(
            "KEY_SWITCH next_key=None pool_size=%d run_errors=%s",
            len(self._keys),
            {str(k): v for k, v in self._run_errors.items()},
        )
        return None

    def mark_error(self, key_id: _uuid.UUID) -> None:
        self._run_errors[key_id] = self._run_errors.get(key_id, 0) + 1

    def mark_success(self, key_id: _uuid.UUID) -> None:
        self._run_errors.pop(key_id, None)

    def flush_to_db(self) -> None:
        """Persist accumulated error/success signals to the database."""
        from backend.database.base import SessionLocal

        seen_success = {k["id"] for k in self._keys} - set(self._run_errors.keys())
        try:
            with SessionLocal() as db:
                for key_id in seen_success:
                    record_key_success_sync(db, key_id)
                for key_id, count in self._run_errors.items():
                    if count > 0:
                        record_key_error_sync(db, key_id)
        except Exception as exc:
            logger.warning("KeyPool flush_to_db failed: %s", exc)
