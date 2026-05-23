"""
Canvas Permission Service
=========================
Validates that the current Canvas access token has permission to access
a specific course before returning indexed data.

Prevents authorization bypass when:
- User changes Canvas token to one without course access
- Token expires or permissions are revoked on Canvas LMS side
- User attempts to access indexed data from courses they no longer belong to

Uses a 5-minute TTL cache to avoid Canvas API rate limiting.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class CanvasPermissionService:
    """Validate user's current Canvas token has access to a course."""

    def __init__(self, cache_ttl_minutes: int = 5):
        # Cache: { "token_prefix:course_id": (has_access, cached_at) }
        self._cache: dict[str, tuple[bool, datetime]] = {}
        self._cache_ttl = timedelta(minutes=cache_ttl_minutes)

    async def validate_course_access(
        self,
        canvas_base_url: str,
        canvas_token: str,
        course_id: int | str,
    ) -> bool:
        """
        Check if the given token has access to the course.

        Returns True if accessible, raises 403 if not.
        On network error: fail-open (returns True with warning).
        """
        course_id_str = str(course_id)
        # Use token prefix as cache key (avoid storing full token in memory)
        cache_key = f"{canvas_token[:12]}:{course_id_str}"

        # ── Check cache ──
        cached = self._cache.get(cache_key)
        if cached is not None:
            has_access, cached_at = cached
            if datetime.now() - cached_at < self._cache_ttl:
                if not has_access:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            f"Current Canvas token does not have access to course {course_id_str}. "
                            "Please reconnect with a valid token."
                        ),
                    )
                return True
            # Expired — remove
            del self._cache[cache_key]

        # ── Call Canvas API ──
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{canvas_base_url.rstrip('/')}/api/v1/courses/{course_id_str}",
                    headers={"Authorization": f"Bearer {canvas_token}"},
                    timeout=10.0,
                )

            has_access = resp.status_code == 200
            self._cache[cache_key] = (has_access, datetime.now())

            if not has_access:
                logger.warning(
                    "Canvas permission denied: token=%s... course=%s status=%d",
                    canvas_token[:8],
                    course_id_str,
                    resp.status_code,
                )
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Current Canvas token does not have access to course {course_id_str}. "
                        f"Canvas returned HTTP {resp.status_code}."
                    ),
                )
            return True

        except HTTPException:
            raise  # Re-raise our own 403

        except httpx.RequestError as exc:
            # Network error — fail open (degraded mode)
            logger.warning(
                "Canvas permission check failed (network): course=%s error=%s — failing open",
                course_id_str,
                str(exc),
            )
            return True

        except Exception as exc:
            logger.error(
                "Unexpected error during Canvas permission check: %s", str(exc),
            )
            return True

    async def filter_accessible_courses(
        self,
        canvas_base_url: str,
        canvas_token: str,
        course_ids: list[str],
    ) -> list[str]:
        """
        Given a list of course_ids, return only those the token can access.
        Uses concurrent checks for faster filtering.
        """
        import asyncio

        async def _check(cid: str) -> str | None:
            try:
                await self.validate_course_access(canvas_base_url, canvas_token, cid)
                return cid
            except HTTPException:
                return None

        results = await asyncio.gather(*[_check(cid) for cid in course_ids])
        return [cid for cid in results if cid is not None]

    def invalidate_cache(self, canvas_token: Optional[str] = None):
        """Clear cache, optionally scoped to a single token."""
        if canvas_token:
            prefix = canvas_token[:12]
            to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in to_remove:
                del self._cache[k]
        else:
            self._cache.clear()

    # ────────────────────────────────────────────────────────────────────
    # V2: Role-based gating for course-domain mutations
    # ────────────────────────────────────────────────────────────────────

    # Canvas enrollment role names that imply ability to manage the course.
    PRIVILEGED_ROLES: frozenset = frozenset({
        "teacher", "TeacherEnrollment",
        "ta", "TaEnrollment",
        "designer", "DesignerEnrollment",
    })

    async def get_course_roles(
        self,
        canvas_base_url: str,
        canvas_token: str,
        course_id,
    ) -> set:
        """Return the set of normalized role names the current token has on
        the given course. Empty set means student or no enrollment.

        Cached separately from access checks (5 min TTL).
        """
        course_id_str = str(course_id)
        cache_key = f"roles:{canvas_token[:12]}:{course_id_str}"

        cached = self._cache.get(cache_key)
        if cached is not None:
            roles_obj, cached_at = cached  # type: ignore[misc]
            if datetime.now() - cached_at < self._cache_ttl:
                return set(roles_obj) if roles_obj else set()
            del self._cache[cache_key]

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{canvas_base_url.rstrip('/')}/api/v1/courses/{course_id_str}",
                    headers={"Authorization": f"Bearer {canvas_token}"},
                    params={"include[]": "enrollments"},
                    timeout=10.0,
                )
            if resp.status_code != 200:
                logger.warning(
                    "Canvas roles lookup failed: course=%s status=%d",
                    course_id_str, resp.status_code,
                )
                self._cache[cache_key] = (frozenset(), datetime.now())  # type: ignore[misc]
                return set()
            data = resp.json()
            enrollments = data.get("enrollments") or []
            roles: set = set()
            for e in enrollments:
                rt = e.get("role") or e.get("type")
                if rt:
                    roles.add(str(rt))
            self._cache[cache_key] = (frozenset(roles), datetime.now())  # type: ignore[misc]
            return roles
        except httpx.RequestError as exc:
            logger.warning(
                "Canvas roles lookup network error course=%s err=%s — assuming no privileged role",
                course_id_str, exc,
            )
            return set()
        except Exception as exc:
            logger.error("Unexpected Canvas roles lookup error: %s", exc)
            return set()

    async def require_privileged_role(
        self,
        canvas_base_url: str,
        canvas_token: str,
        course_id,
    ) -> set:
        """Raise 403 INSUFFICIENT_ROLE unless the token holds at least one
        of ``PRIVILEGED_ROLES`` on the course. Returns the role set on success.
        """
        roles = await self.get_course_roles(canvas_base_url, canvas_token, course_id)
        if not (roles & self.PRIVILEGED_ROLES):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "INSUFFICIENT_ROLE",
                    "message": (
                        "Only teachers, TAs, or course designers can manage "
                        "course-shared domain knowledge."
                    ),
                    "course_id": str(course_id),
                    "actual_roles": sorted(roles),
                },
            )
        return roles


# ── Singleton ──
canvas_permission = CanvasPermissionService()
