"""
Server-side Canvas connection resolution.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.security import decrypt_token
from backend.database.base import AsyncSessionLocal, SessionLocal
from backend.database.models import CanvasToken
from backend.services.canvas_headers import extract_canvas_headers
from backend.services.url_safety import validate_canvas_origin_url

logger = logging.getLogger(__name__)


def _legacy_mode_enabled() -> bool:
    return settings.CANVAS_SERVER_SIDE_MODE == "dual"


def _normalize_domain_hint(canvas_domain_hint: Optional[str]) -> Optional[str]:
    if not canvas_domain_hint:
        return None
    return validate_canvas_origin_url(canvas_domain_hint)


def _query_active_canvas_token(
    db: AsyncSession | Session,
    *,
    user_id: UUID,
    canvas_domain_hint: Optional[str],
):
    stmt = (
        select(CanvasToken)
        .where(CanvasToken.user_id == user_id)
        .where(CanvasToken.revoked_at.is_(None))
    )
    if canvas_domain_hint:
        stmt = stmt.where(CanvasToken.canvas_domain == canvas_domain_hint)
    return stmt.order_by(CanvasToken.created_at.desc())


async def _resolve_async_with_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    request: Optional[Request],
    canvas_domain_hint: Optional[str],
    require: bool,
    owns_session: bool,
) -> tuple[Optional[str], Optional[str]]:
    normalized_hint = _normalize_domain_hint(canvas_domain_hint)

    stmt = _query_active_canvas_token(
        db,
        user_id=user_id,
        canvas_domain_hint=normalized_hint,
    ).limit(2)
    result = await db.execute(stmt)
    tokens = list(result.scalars().all())

    if tokens:
        if len(tokens) > 1 and normalized_hint is None:
            logger.warning(
                "Multiple active Canvas tokens found for user=%s with no domain hint; using newest token",
                user_id,
            )

        token = tokens[0]
        token.update_last_used()
        if owns_session:
            await db.commit()
        else:
            await db.flush()
        return decrypt_token(token.access_token_encrypted), token.canvas_domain

    if request is not None and _legacy_mode_enabled():
        legacy_base_url, legacy_token = extract_canvas_headers(request)
        if legacy_token:
            base_url = validate_canvas_origin_url(
                legacy_base_url or settings.DEFAULT_CANVAS_BASE_URL
            )
            logger.warning(
                "Using deprecated Canvas header fallback for user=%s path=%s",
                user_id,
                request.url.path,
            )
            return legacy_token, base_url

    if require:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Canvas connection not configured. Please connect a Canvas token in Settings.",
        )
    return None, None


async def resolve_canvas_connection_async(
    *,
    user_id: UUID | str | None,
    request: Optional[Request] = None,
    canvas_domain_hint: Optional[str] = None,
    require: bool = True,
    db: Optional[AsyncSession] = None,
) -> tuple[Optional[str], Optional[str]]:
    if user_id is None:
        if request is not None and _legacy_mode_enabled():
            legacy_base_url, legacy_token = extract_canvas_headers(request)
            if legacy_token:
                base_url = validate_canvas_origin_url(
                    legacy_base_url or settings.DEFAULT_CANVAS_BASE_URL
                )
                return legacy_token, base_url
        if require:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Canvas connection not configured. Please connect a Canvas token in Settings.",
            )
        return None, None

    owns_session = db is None
    user_uuid = UUID(str(user_id))

    if db is not None:
        return await _resolve_async_with_session(
            db,
            user_id=user_uuid,
            request=request,
            canvas_domain_hint=canvas_domain_hint,
            require=require,
            owns_session=False,
        )

    async with AsyncSessionLocal() as session:
        return await _resolve_async_with_session(
            session,
            user_id=user_uuid,
            request=request,
            canvas_domain_hint=canvas_domain_hint,
            require=require,
            owns_session=owns_session,
        )


def _resolve_sync_with_session(
    db: Session,
    *,
    user_id: UUID,
    canvas_domain_hint: Optional[str],
    legacy_token: Optional[str],
    legacy_base_url: Optional[str],
    require: bool,
    owns_session: bool,
) -> tuple[Optional[str], Optional[str]]:
    normalized_hint = _normalize_domain_hint(canvas_domain_hint)

    stmt = _query_active_canvas_token(
        db,
        user_id=user_id,
        canvas_domain_hint=normalized_hint,
    ).limit(2)
    result = db.execute(stmt)
    tokens = list(result.scalars().all())

    if tokens:
        if len(tokens) > 1 and normalized_hint is None:
            logger.warning(
                "Multiple active Canvas tokens found for user=%s with no domain hint; using newest token",
                user_id,
            )
        token = tokens[0]
        token.update_last_used()
        if owns_session:
            db.commit()
        else:
            db.flush()
        return decrypt_token(token.access_token_encrypted), token.canvas_domain

    if _legacy_mode_enabled() and legacy_token:
        base_url = validate_canvas_origin_url(
            legacy_base_url or settings.DEFAULT_CANVAS_BASE_URL
        )
        logger.warning(
            "Using deprecated Canvas secret fallback inside worker for user=%s",
            user_id,
        )
        return legacy_token, base_url

    if require:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Canvas connection not configured. Please connect a Canvas token in Settings.",
        )
    return None, None


def resolve_canvas_connection_sync(
    *,
    user_id: UUID | str | None,
    canvas_domain_hint: Optional[str] = None,
    legacy_token: Optional[str] = None,
    legacy_base_url: Optional[str] = None,
    require: bool = True,
    db: Optional[Session] = None,
) -> tuple[Optional[str], Optional[str]]:
    if user_id is None:
        if _legacy_mode_enabled() and legacy_token:
            base_url = validate_canvas_origin_url(
                legacy_base_url or settings.DEFAULT_CANVAS_BASE_URL
            )
            return legacy_token, base_url
        if require:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Canvas connection not configured. Please connect a Canvas token in Settings.",
            )
        return None, None

    owns_session = db is None
    user_uuid = UUID(str(user_id))

    if db is not None:
        return _resolve_sync_with_session(
            db,
            user_id=user_uuid,
            canvas_domain_hint=canvas_domain_hint,
            legacy_token=legacy_token,
            legacy_base_url=legacy_base_url,
            require=require,
            owns_session=False,
        )

    with SessionLocal() as session:
        return _resolve_sync_with_session(
            session,
            user_id=user_uuid,
            canvas_domain_hint=canvas_domain_hint,
            legacy_token=legacy_token,
            legacy_base_url=legacy_base_url,
            require=require,
            owns_session=owns_session,
        )
