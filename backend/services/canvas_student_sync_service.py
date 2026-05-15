"""
canvas_student_sync_service
===========================

Pure DB-side sync helpers that mirror Canvas user + enrollment payloads
into the local ``canvas_students`` / ``canvas_student_enrollments`` tables.

Hard rules (do NOT relax without an explicit task):

* Match between an Excel row and a Canvas user must be EXACT on at least
  one of:

      ``login_id``      == generated_email
      ``email``         == generated_email
      ``sis_user_id``   == student_code

  Substring / fuzzy / "name contains" matches are rejected.

* If Canvas search returns ≥ 2 distinct users that all match exactly,
  the row is flagged ``ambiguous_canvas_match`` and NO sync is performed.

* The simulation tables (``test_students``, ``simulation_runs``,
  ``canvas_audit_log``) are NEVER read or written here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    CanvasStudent,
    CanvasStudentEnrollment,
)
from backend.services import canvas_service

logger = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────────────

class MatchResult:
    """Plain-data return of :func:`find_exact_canvas_user`."""

    __slots__ = ("status", "user", "candidates", "needed_profile_fetch", "old_account")

    def __init__(
        self,
        status: str,
        user: Optional[dict] = None,
        candidates: Optional[list[dict]] = None,
        needed_profile_fetch: bool = False,
        old_account: Optional[dict] = None,
    ) -> None:
        # status ∈ {"matched", "not_found", "ambiguous"}
        self.status = status
        self.user = user
        self.candidates = candidates or []
        self.needed_profile_fetch = needed_profile_fetch
        # Canvas user matching the OLD {MSSV}@vnu.edu.vn / sis_user_id pattern
        # (informational warning only — does NOT block new sv-email creation)
        self.old_account = old_account


# ── Field extraction helpers ──────────────────────────────────────────────

def _norm(s: Any) -> str:
    return str(s).strip().lower() if s is not None else ""


def _user_login(u: dict) -> str:
    return _norm(u.get("login_id"))


def _user_email(u: dict) -> str:
    # Canvas search response uses "email" (top-level) or sometimes
    # "primary_email" (profile endpoint).
    return _norm(u.get("email") or u.get("primary_email"))


def _user_sis(u: dict) -> str:
    return _norm(u.get("sis_user_id"))


def _sv_email_matches(u: dict, *, generated_email: str) -> bool:
    """Exact match on the NEW sv-prefixed email only (login or email field)."""
    ge = _norm(generated_email)
    return ge != "" and (
        _user_login(u) == ge or _user_email(u) == ge
    )


def _row_matches(u: dict, *, generated_email: str, student_code: str) -> bool:
    """Legacy alias kept for external callers; now delegates to sv-email match only."""
    return _sv_email_matches(u, generated_email=generated_email)


def _is_old_account(u: dict, *, student_code: str, generated_email: str) -> bool:
    """
    True if the user looks like the *old* {MSSV}@vnu.edu.vn account:
    - login_id or email matches the bare MSSV email (no sv prefix), OR
    - sis_user_id matches student_code
    AND the user does NOT match the new sv-prefixed email.
    """
    if _sv_email_matches(u, generated_email=generated_email):
        return False  # this IS the new account, not old
    sc = _norm(student_code)
    old_email = f"{sc}@vnu.edu.vn" if sc else ""
    return (
        (old_email and (_user_login(u) == old_email or _user_email(u) == old_email))
        or (sc and _user_sis(u) == sc)
    )


def _missing_match_fields(u: dict) -> bool:
    """True when the user dict lacks all three matchable fields."""
    return not (_user_login(u) or _user_email(u) or _user_sis(u))


# ── Exact-match search ────────────────────────────────────────────────────

async def find_exact_canvas_user(
    *,
    token: str,
    base_url: str,
    account_id: int | str,
    student_code: str,
    generated_email: str,
) -> MatchResult:
    """
    Search Canvas for a user that EXACTLY matches the new sv-prefixed email.

    Strategy:

    1. ``search_term = generated_email``  (sv{MSSV}@vnu.edu.vn)
    2. ``search_term = student_code``     (to surface old account if any)
    3. Filter NEW-account candidates via ``_sv_email_matches``.
    4. Collect any OLD-account candidates via ``_is_old_account``.
    5. Dedupe by ``id``.  len==0 → not_found, ==1 → matched, ≥2 → ambiguous.
    6. If a hit is missing all matchable fields, fetch its profile once.
    """
    seen_ids: set[int] = set()
    candidates: list[dict] = []      # new sv-email matches
    old_candidates: list[dict] = []  # old MSSV-email / SIS matches
    seen_old_ids: set[int] = set()
    needed_profile_fetch = False

    for term in (generated_email, student_code):
        if not term:
            continue
        resp = await canvas_service.search_account_users(
            token, base_url, account_id, term, per_page=20
        )
        if not resp.get("success"):
            logger.warning(
                "search_account_users failed for term=%r: %s",
                term, resp.get("error"),
            )
            continue

        for raw in resp.get("users", []):
            uid = raw.get("id")
            if uid is None:
                continue

            user = raw
            if _missing_match_fields(user):
                profile = await canvas_service.get_canvas_user_profile(
                    token, base_url, uid
                )
                needed_profile_fetch = True
                if profile.get("success") and profile.get("user"):
                    user = {**raw, **profile["user"]}

            if uid not in seen_ids and _sv_email_matches(
                user, generated_email=generated_email
            ):
                seen_ids.add(uid)
                candidates.append(user)
            elif uid not in seen_old_ids and _is_old_account(
                user, student_code=student_code, generated_email=generated_email
            ):
                seen_old_ids.add(uid)
                old_candidates.append(user)

    # Pick best old account (first one found, if any)
    old_account = old_candidates[0] if old_candidates else None

    if not candidates:
        return MatchResult(
            "not_found",
            needed_profile_fetch=needed_profile_fetch,
            old_account=old_account,
        )
    if len(candidates) == 1:
        return MatchResult(
            "matched",
            user=candidates[0],
            needed_profile_fetch=needed_profile_fetch,
            old_account=old_account,
        )
    return MatchResult(
        "ambiguous",
        candidates=candidates,
        needed_profile_fetch=needed_profile_fetch,
        old_account=old_account,
    )


# ── DB upsert helpers ─────────────────────────────────────────────────────

def _derive_student_code(canvas_user: dict, hint_code: Optional[str]) -> Optional[str]:
    """Prefer sis_user_id, fall back to a numeric/alphanumeric login_id, finally hint."""
    sis = (canvas_user.get("sis_user_id") or "").strip()
    if sis:
        return sis
    login = (canvas_user.get("login_id") or "").strip()
    if login and "@" not in login:
        return login
    return (hint_code or None)


async def upsert_canvas_student(
    db: AsyncSession,
    *,
    canvas_domain: str,
    owner_id: UUID,
    canvas_user: dict,
    source: str,
    hint_student_code: Optional[str] = None,
    hint_full_name: Optional[str] = None,
) -> CanvasStudent:
    """
    Insert or update a ``canvas_students`` row, keyed on
    (canvas_domain, canvas_user_id).

    Caller must commit/flush. We only ``add`` and ``flush`` so the PK is
    populated for downstream FK references (rows + enrollments).
    """
    canvas_user_id = int(canvas_user["id"])
    now = datetime.now(timezone.utc)

    full_name = (
        canvas_user.get("name")
        or canvas_user.get("sortable_name")
        or hint_full_name
        or "(unknown)"
    )
    student_code = _derive_student_code(canvas_user, hint_student_code)
    sis_user_id = (canvas_user.get("sis_user_id") or None)
    login_id = (canvas_user.get("login_id") or None)
    email = (
        canvas_user.get("email")
        or canvas_user.get("primary_email")
        or None
    )

    # 1) Primary lookup: (canvas_domain, canvas_user_id)
    stmt = select(CanvasStudent).where(
        CanvasStudent.canvas_domain == canvas_domain,
        CanvasStudent.canvas_user_id == canvas_user_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    # 2) Secondary lookup: (canvas_domain, student_code)
    #    Required to avoid violating uq_canvas_students_domain_code when the
    #    Canvas user_id has changed (old account replaced by fresh sv-email
    #    account) but MSSV is the same.
    if existing is None and student_code:
        stmt2 = select(CanvasStudent).where(
            CanvasStudent.canvas_domain == canvas_domain,
            CanvasStudent.student_code == student_code,
        )
        existing = (await db.execute(stmt2)).scalar_one_or_none()
        if existing is not None:
            # Re-bind the local record to the new Canvas user.
            existing.canvas_user_id = canvas_user_id

    if existing is None:
        row = CanvasStudent(
            owner_id=owner_id,
            canvas_domain=canvas_domain,
            canvas_user_id=canvas_user_id,
            student_code=student_code,
            sis_user_id=sis_user_id,
            login_id=login_id,
            email=email,
            full_name=full_name,
            source=source,
            last_synced_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    # Update fields. For login_id/email we ALWAYS overwrite when a fresh
    # value is supplied — the previous value may belong to the old account.
    if student_code:
        existing.student_code = student_code
    if sis_user_id:
        existing.sis_user_id = sis_user_id
    if login_id:
        existing.login_id = login_id
    if email:
        existing.email = email
    if full_name and full_name != "(unknown)":
        existing.full_name = full_name
    if source:
        existing.source = source
    existing.last_synced_at = now
    await db.flush()
    return existing


async def upsert_enrollment(
    db: AsyncSession,
    *,
    canvas_student_id: UUID,
    canvas_domain: str,
    course_id: int,
    enrollment: dict,
) -> CanvasStudentEnrollment:
    """
    Upsert a ``canvas_student_enrollments`` row, keyed on
    (canvas_domain, canvas_enrollment_id).
    """
    canvas_enrollment_id = int(enrollment["id"])
    enrollment_state = (enrollment.get("enrollment_state") or "").strip() or "active"
    enrollment_type = enrollment.get("type") or "StudentEnrollment"
    now = datetime.now(timezone.utc)

    stmt = select(CanvasStudentEnrollment).where(
        CanvasStudentEnrollment.canvas_domain == canvas_domain,
        CanvasStudentEnrollment.canvas_enrollment_id == canvas_enrollment_id,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing is None:
        row = CanvasStudentEnrollment(
            canvas_student_id=canvas_student_id,
            canvas_domain=canvas_domain,
            course_id=course_id,
            canvas_enrollment_id=canvas_enrollment_id,
            enrollment_type=enrollment_type,
            enrollment_state=enrollment_state,
            last_synced_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    existing.enrollment_state = enrollment_state
    existing.enrollment_type = enrollment_type
    existing.last_synced_at = now
    await db.flush()
    return existing


async def sync_course_enrollments(
    db: AsyncSession,
    *,
    canvas_student_id: UUID,
    canvas_domain: str,
    course_id: int,
    enrollments: Iterable[dict],
) -> list[CanvasStudentEnrollment]:
    """Bulk upsert. Caller already fetched the list from Canvas."""
    out: list[CanvasStudentEnrollment] = []
    for e in enrollments:
        if not e or not e.get("id"):
            continue
        out.append(
            await upsert_enrollment(
                db,
                canvas_student_id=canvas_student_id,
                canvas_domain=canvas_domain,
                course_id=course_id,
                enrollment=e,
            )
        )
    return out


# ── Quick existence lookup (used by import preview) ──────────────────────

async def find_local_student(
    db: AsyncSession,
    *,
    canvas_domain: str,
    student_code: Optional[str] = None,
    generated_email: Optional[str] = None,
) -> Optional[CanvasStudent]:
    """Look up an existing local mirror by code or email (case-insensitive on email)."""
    if student_code:
        stmt = select(CanvasStudent).where(
            CanvasStudent.canvas_domain == canvas_domain,
            CanvasStudent.student_code == student_code,
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row:
            return row

    if generated_email:
        stmt = select(CanvasStudent).where(
            CanvasStudent.canvas_domain == canvas_domain,
            CanvasStudent.email == generated_email.lower(),
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row:
            return row

    return None
