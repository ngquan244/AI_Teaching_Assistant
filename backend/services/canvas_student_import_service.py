"""
canvas_student_import_service
=============================

Excel-driven student import / enroll orchestrator.

Two flows share a preview→confirm UX:

* mode=create
    - preview:  Validate file, classify each row (DB hit / Canvas hit /
                new). NO DB writes for new rows. NO Canvas mutations.
    - confirm:  For each ``valid_new_user`` row → create the Canvas user
                (no auto_unique, no '+sim' email mangling). If
                ``enroll_after_create=true`` and a course is set, also
                enroll the new user. For ``existed_on_canvas`` rows that
                turned up during preview, sync to DB and (optionally,
                ``enroll_existing=true``) enroll.

* mode=enroll
    - preview:  Resolve each row to a Canvas user; sync the matched user
                into the DB so the enrollment-state lookup can attach to
                a stable canvas_student_id; return current per-course
                enrollment state.
    - confirm:  Enroll rows whose status is ``enroll_ready``. Skip
                ``already_enrolled`` and ``enrollment_completed``;
                reactivate ``enrollment_inactive`` only when
                ``reactivate_inactive=true``; recreate
                ``enrollment_deleted`` only when ``recreate_deleted=true``.

Hard rules:
* The simulation tables are NEVER read or written.
* ``canvas_service.create_canvas_user`` is invoked WITHOUT the
  ``+sim<uuid>`` retry — we want the original email or a clean failure.
* If Canvas rejects ``sis_user_id`` (HTTP 400 with sis-related error),
  retry once without it.
* Confirm is idempotent at the batch level: a second confirm returns
  ``BATCH_ALREADY_CONFIRMED`` without re-touching Canvas.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import (
    CanvasStudent,
    CanvasStudentEnrollment,
    StudentImportBatch,
    StudentImportRow,
    BatchStatus,
    ImportMode,
    RowStatus,
)
from backend.database.models.canvas_simulation import (
    AuditAction,
    CanvasAuditLog,
)
from backend.services import canvas_service
from backend.services import canvas_student_sync_service as sync_svc
from backend.utils.excel_student_parser import (
    ParsedRow,
    parse_student_excel,
)

logger = logging.getLogger(__name__)

# Cap concurrent Canvas calls to be polite.
CANVAS_CONCURRENCY = 3
PREVIEW_TTL = timedelta(hours=24)

# Friendly error code returned to clients.
ERR_BATCH_NOT_FOUND = "BATCH_NOT_FOUND"
ERR_BATCH_FORBIDDEN = "BATCH_FORBIDDEN"
ERR_BATCH_ALREADY_CONFIRMED = "BATCH_ALREADY_CONFIRMED"
ERR_BATCH_EXPIRED = "BATCH_EXPIRED"
ERR_BATCH_INVALID_STATE = "BATCH_INVALID_STATE"
ERR_NO_COURSE_FOR_ENROLL = "NO_COURSE_FOR_ENROLL"


# ── Audit helper ──────────────────────────────────────────────────────────

async def _audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: AuditAction,
    canvas_domain: str,
    success: bool,
    canvas_course_id: int | None = None,
    canvas_user_id: int | None = None,
    detail: dict | str | None = None,
) -> None:
    payload: str | None
    if isinstance(detail, dict):
        payload = json.dumps(detail, ensure_ascii=False, default=str)
    else:
        payload = detail
    db.add(
        CanvasAuditLog(
            user_id=user_id,
            action=action,
            canvas_domain=canvas_domain,
            canvas_course_id=canvas_course_id,
            canvas_user_id=canvas_user_id,
            success=success,
            detail=payload,
        )
    )


# ── Summary builder ───────────────────────────────────────────────────────

def _build_summary(rows: list[StudentImportRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
    out["_total"] = len(rows)
    return out


# ── PREVIEW ───────────────────────────────────────────────────────────────

async def preview_import(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
    mode: str,
    canvas_domain: str,
    account_id: int,
    course_id: Optional[int],
    enroll_after_create: bool,
    enroll_existing: bool,
    token: str,
    base_url: str,
) -> StudentImportBatch:
    """Parse + classify; persist a preview batch and return it (with rows)."""
    if mode not in (ImportMode.CREATE, ImportMode.ENROLL):
        raise ValueError(f"Unsupported mode: {mode!r}")
    if mode == ImportMode.ENROLL and not course_id:
        raise ValueError("course_id is required when mode=enroll")

    parsed = parse_student_excel(file_bytes)

    batch = StudentImportBatch(
        owner_id=owner_id,
        canvas_domain=canvas_domain,
        account_id=account_id,
        course_id=course_id,
        mode=mode,
        filename=filename,
        status=BatchStatus.PREVIEW,
        total_rows=len(parsed.rows),
        enroll_after_create=enroll_after_create,
        enroll_existing=enroll_existing,
        expires_at=datetime.now(timezone.utc) + PREVIEW_TTL,
    )
    db.add(batch)
    await db.flush()  # populate batch.id

    # Pre-create row stubs so we can mutate them in classification loop.
    db_rows: list[StudentImportRow] = []
    for p in parsed.rows:
        db_rows.append(
            StudentImportRow(
                batch_id=batch.id,
                row_number=p.row_number,
                student_code=p.student_code,
                full_name=p.full_name,
                generated_email=p.generated_email,
                status=RowStatus.INVALID,  # default, will refine
                error_code=p.error_code,
                message=p.message,
            )
        )
    db.add_all(db_rows)
    await db.flush()

    # Classify
    sem = asyncio.Semaphore(CANVAS_CONCURRENCY)

    async def _classify(parsed_row: ParsedRow, db_row: StudentImportRow) -> None:
        async with sem:
            await _classify_row(
                db,
                parsed_row=parsed_row,
                db_row=db_row,
                mode=mode,
                canvas_domain=canvas_domain,
                account_id=account_id,
                course_id=course_id,
                token=token,
                base_url=base_url,
                owner_id=owner_id,
            )

    await asyncio.gather(
        *(_classify(p, r) for p, r in zip(parsed.rows, db_rows)),
        return_exceptions=False,
    )

    batch.summary = _build_summary(db_rows)
    await db.flush()
    return batch


async def _classify_row(
    db: AsyncSession,
    *,
    parsed_row: ParsedRow,
    db_row: StudentImportRow,
    mode: str,
    canvas_domain: str,
    account_id: int,
    course_id: Optional[int],
    token: str,
    base_url: str,
    owner_id: uuid.UUID,
) -> None:
    # File-level validation already failed → leave invalid.
    if parsed_row.error_code:
        if parsed_row.error_code == "duplicate_in_file":
            db_row.status = RowStatus.DUPLICATE_IN_FILE
        else:
            db_row.status = RowStatus.INVALID
        return

    if not parsed_row.is_valid:
        db_row.status = RowStatus.INVALID
        return

    student_code = parsed_row.student_code or ""
    generated_email = parsed_row.generated_email or ""

    # Guard: sv-email format must match (belt-and-suspenders after parser)
    import re as _re
    if not _re.match(r"^sv[A-Za-z0-9]+@vnu\.edu\.vn$", generated_email):
        db_row.status = RowStatus.INVALID
        db_row.error_code = "invalid_generated_email"
        db_row.message = "Email sinh vien không đúng định dạng sv{MSSV}@vnu.edu.vn."
        return
    if student_code.upper().startswith("PH"):
        db_row.status = RowStatus.INVALID
        db_row.error_code = "ph_account_blocked"
        db_row.message = "MSSV bắt đầu bằng PH (observer/phụ huynh) — không được import."
        return

    # 1. Fast local DB lookup — ONLY by new sv-email (blocks duplicate sv accounts)
    local_by_email = await sync_svc.find_local_student(
        db,
        canvas_domain=canvas_domain,
        generated_email=generated_email,
    )
    # Also check if DB has a *stale* entry keyed on student_code with different email
    local_by_code: Any = None
    if local_by_email is None:
        local_by_code = await sync_svc.find_local_student(
            db,
            canvas_domain=canvas_domain,
            student_code=student_code,
        )
        if local_by_code is not None and (
            (local_by_code.email or "").lower() == generated_email.lower()
        ):
            # Same sv-email stored under student_code lookup → treat as email match
            local_by_email = local_by_code
            local_by_code = None

    # 2. Canvas exact-match search (sv-email only; detects old account separately)
    match = await sync_svc.find_exact_canvas_user(
        token=token,
        base_url=base_url,
        account_id=account_id,
        student_code=student_code,
        generated_email=generated_email,
    )

    if match.status == "ambiguous":
        db_row.status = RowStatus.INVALID
        db_row.error_code = "ambiguous_canvas_match"
        db_row.message = (
            f"Có {len(match.candidates)} user trên Canvas khớp chính xác — "
            "không thể tự động chọn."
        )
        return

    # ── mode=create classification ────────────────────────────────────
    if mode == ImportMode.CREATE:
        if local_by_email is not None:
            db_row.status = RowStatus.EXISTED_IN_DB
            db_row.canvas_user_id = local_by_email.canvas_user_id
            db_row.canvas_student_id = local_by_email.id
            db_row.message = "Đã có trong DB nội bộ (sv-email khớp)."
            return
        if match.status == "matched" and match.user is not None:
            # sv-email already on Canvas → block
            db_row.status = RowStatus.EXISTED_ON_CANVAS
            db_row.canvas_user_id = int(match.user["id"])
            db_row.message = "Đã tồn tại trên Canvas (sv-email khớp)."
            return
        # Stale old DB entry (different email, not sv-prefix)
        if local_by_code is not None:
            db_row.status = RowStatus.STALE_OLD_ACCOUNT
            db_row.canvas_user_id = local_by_code.canvas_user_id
            db_row.canvas_student_id = local_by_code.id
            old_email = local_by_code.email or "?"
            old_canvas_msg = ""
            if match.old_account:
                old_canvas_msg = f" Trên Canvas cũng phát hiện account cũ (ID {match.old_account.get('id')})."
            db_row.message = (
                f"DB có bản ghi cũ (email={old_email}); sẽ tạo account mới sv-email.{old_canvas_msg}"
            )
            return
        # Old Canvas account only (no DB entry, no sv-email match)
        if match.old_account is not None:
            db_row.status = RowStatus.OLD_ACCOUNT_EXISTS
            db_row.message = (
                f"Có account cũ theo MSSV/SIS (Canvas ID {match.old_account.get('id')}); "
                "sẽ tạo account mới dạng sv-email không có sis_user_id."
            )
            return
        # Truly new
        db_row.status = RowStatus.VALID_NEW_USER
        return

    # ── mode=enroll classification ────────────────────────────────────
    # mode=enroll requires a Canvas user; if not found → terminal error.
    if match.status != "matched" or match.user is None:
        db_row.status = RowStatus.USER_NOT_FOUND_ON_CANVAS
        db_row.message = "Không tìm thấy user khớp chính xác (sv-email) trên Canvas."
        return

    canvas_user = match.user

    # Sync to DB so we have a stable canvas_student_id for the enrollment row.
    student = await sync_svc.upsert_canvas_student(
        db,
        canvas_domain=canvas_domain,
        owner_id=owner_id,
        canvas_user=canvas_user,
        source=("synced_from_canvas" if local is None else local.source),
        hint_student_code=student_code,
        hint_full_name=parsed_row.full_name,
    )
    db_row.canvas_student_id = student.id
    db_row.canvas_user_id = student.canvas_user_id

    # Look up current enrollments in this course
    assert course_id is not None
    er = await canvas_service.list_user_enrollments_in_course(
        token, base_url, course_id, student.canvas_user_id
    )
    if not er.get("success"):
        db_row.status = RowStatus.FAILED
        db_row.error_code = "enrollment_lookup_failed"
        db_row.message = er.get("error") or "Không thể truy vấn enrollment."
        return

    enrollments: list[dict] = er.get("enrollments") or []
    await sync_svc.sync_course_enrollments(
        db,
        canvas_student_id=student.id,
        canvas_domain=canvas_domain,
        course_id=course_id,
        enrollments=enrollments,
    )

    state = _strongest_enrollment_state(enrollments)
    if state is None:
        db_row.status = RowStatus.ENROLL_READY
    elif state == "active" or state == "invited":
        db_row.status = RowStatus.ALREADY_ENROLLED
        db_row.canvas_enrollment_id = _pick_enrollment_id(enrollments, state)
    elif state == "inactive":
        db_row.status = RowStatus.ENROLLMENT_INACTIVE
        db_row.canvas_enrollment_id = _pick_enrollment_id(enrollments, state)
    elif state == "completed":
        db_row.status = RowStatus.ENROLLMENT_COMPLETED
        db_row.canvas_enrollment_id = _pick_enrollment_id(enrollments, state)
    elif state == "deleted":
        db_row.status = RowStatus.ENROLLMENT_DELETED
    else:
        db_row.status = RowStatus.ENROLL_READY


def _strongest_enrollment_state(enrollments: list[dict]) -> Optional[str]:
    """Return the highest-priority state, mirroring Canvas's own ordering."""
    priority = ["active", "invited", "inactive", "completed", "deleted"]
    states = {(e.get("enrollment_state") or "").lower() for e in enrollments}
    for s in priority:
        if s in states:
            return s
    return None


def _pick_enrollment_id(enrollments: list[dict], state: str) -> Optional[int]:
    for e in enrollments:
        if (e.get("enrollment_state") or "").lower() == state:
            return e.get("id")
    return None


# ── CONFIRM ───────────────────────────────────────────────────────────────

async def confirm_import(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    batch_id: uuid.UUID,
    token: str,
    base_url: str,
    enroll_after_create: Optional[bool] = None,
    enroll_existing: Optional[bool] = None,
    reactivate_inactive: bool = False,
    recreate_deleted: bool = False,
) -> StudentImportBatch:
    """
    Lock the batch (status preview → in-progress via SELECT … FOR UPDATE),
    execute the queued mutations, then mark confirmed.

    Idempotent: a second call on a confirmed batch returns the batch as-is
    after raising :class:`ConfirmAlreadyDoneError`.
    """
    batch = await _load_batch_for_confirm(db, batch_id=batch_id, owner_id=owner_id)

    # Allow caller to override the toggles set at preview time.
    if enroll_after_create is not None:
        batch.enroll_after_create = enroll_after_create
    if enroll_existing is not None:
        batch.enroll_existing = enroll_existing

    sem = asyncio.Semaphore(CANVAS_CONCURRENCY)  # noqa: F841 (kept for symmetry; not used here)

    # Reload rows eagerly
    rows: list[StudentImportRow] = list(batch.rows)

    # ── SEQUENTIAL processing with SAVEPOINTs ─────────────────────────
    # Why sequential: concurrent coroutines share the same AsyncSession;
    # one IntegrityError would taint the whole transaction
    # (PendingRollbackError for every subsequent row).
    #
    # Why savepoints (begin_nested): a per-row IntegrityError rolls back
    # only the savepoint, leaving the outer transaction healthy so the
    # remaining rows + the final batch.status update still succeed.
    for row in rows:
        # Snapshot primitives BEFORE any DB op so we can still log/update
        # the row even if the ORM object becomes detached after a rollback.
        row_id = row.id
        row_number = row.row_number
        student_code = row.student_code

        savepoint = await db.begin_nested()
        try:
            if batch.mode == ImportMode.CREATE:
                await _confirm_create_row(
                    db,
                    batch=batch,
                    row=row,
                    token=token,
                    base_url=base_url,
                    owner_id=owner_id,
                )
            else:
                await _confirm_enroll_row(
                    db,
                    batch=batch,
                    row=row,
                    token=token,
                    base_url=base_url,
                    owner_id=owner_id,
                    reactivate_inactive=reactivate_inactive,
                    recreate_deleted=recreate_deleted,
                )
            await savepoint.commit()
        except IntegrityError as exc:
            await savepoint.rollback()
            logger.exception(
                "IntegrityError on row %s (code=%s): %s",
                row_number, student_code, exc,
            )
            await _mark_row_failed_savepoint(
                db,
                row_id=row_id,
                error_code="integrity_error",
                message=f"DB conflict: {str(exc.orig) if exc.orig else str(exc)}"[:500],
            )
        except Exception as exc:  # noqa: BLE001 — never let one row crash the batch
            await savepoint.rollback()
            logger.exception("Row %s failed during confirm", row_number)
            await _mark_row_failed_savepoint(
                db,
                row_id=row_id,
                error_code="unhandled_exception",
                message=str(exc)[:500],
            )

    # Re-load rows from session so summary reflects the latest state
    # (rows we marked failed via _mark_row_failed_savepoint may be detached
    # from the original list).
    rows = list((
        await db.execute(
            select(StudentImportRow)
            .where(StudentImportRow.batch_id == batch.id)
            .order_by(StudentImportRow.row_number.asc())
        )
    ).scalars().all())

    batch.status = BatchStatus.CONFIRMED
    batch.confirmed_at = datetime.now(timezone.utc)
    batch.summary = _build_summary(rows)
    await db.flush()
    return batch


async def _mark_row_failed_savepoint(
    db: AsyncSession,
    *,
    row_id: uuid.UUID,
    error_code: str,
    message: str,
) -> None:
    """Re-fetch a row inside its own savepoint and mark it failed.

    Runs inside the outer transaction. Uses a fresh nested savepoint so
    that even if THIS update fails, the outer transaction is unharmed.
    """
    sp = await db.begin_nested()
    try:
        fresh = (
            await db.execute(
                select(StudentImportRow).where(StudentImportRow.id == row_id)
            )
        ).scalar_one_or_none()
        if fresh is None:
            await sp.rollback()
            return
        fresh.status = RowStatus.FAILED
        fresh.error_code = error_code
        fresh.message = message
        await sp.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Could not mark row %s as failed", row_id)
        await sp.rollback()


class ConfirmAlreadyDoneError(Exception):
    """Raised by :func:`confirm_import` on second submit; carries the batch."""

    def __init__(self, batch: StudentImportBatch):
        super().__init__(ERR_BATCH_ALREADY_CONFIRMED)
        self.batch = batch


class BatchNotFoundError(Exception):
    pass


class BatchForbiddenError(Exception):
    pass


class BatchInvalidStateError(Exception):
    def __init__(self, status: str):
        super().__init__(f"Batch is in state {status!r}, cannot confirm.")
        self.status = status


async def _load_batch_for_confirm(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> StudentImportBatch:
    """SELECT … FOR UPDATE on the batch row to serialise confirm calls."""
    stmt = (
        select(StudentImportBatch)
        .where(StudentImportBatch.id == batch_id)
        .options(selectinload(StudentImportBatch.rows))
        .with_for_update()
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise BatchNotFoundError(ERR_BATCH_NOT_FOUND)
    if batch.owner_id != owner_id:
        raise BatchForbiddenError(ERR_BATCH_FORBIDDEN)

    if batch.status == BatchStatus.CONFIRMED:
        raise ConfirmAlreadyDoneError(batch)

    if batch.status != BatchStatus.PREVIEW:
        raise BatchInvalidStateError(batch.status)

    if batch.expires_at and batch.expires_at < datetime.now(timezone.utc):
        batch.status = BatchStatus.EXPIRED
        await db.flush()
        raise BatchInvalidStateError(BatchStatus.EXPIRED)

    return batch


# ── Per-row confirm: CREATE ───────────────────────────────────────────────

async def _confirm_create_row(
    db: AsyncSession,
    *,
    batch: StudentImportBatch,
    row: StudentImportRow,
    token: str,
    base_url: str,
    owner_id: uuid.UUID,
) -> None:
    if row.status not in (
        RowStatus.VALID_NEW_USER,
        RowStatus.OLD_ACCOUNT_EXISTS,
        RowStatus.STALE_OLD_ACCOUNT,
        RowStatus.EXISTED_ON_CANVAS,
        RowStatus.EXISTED_IN_DB,
    ):
        # invalid / duplicate / failed: skip
        return

    canvas_domain = batch.canvas_domain
    account_id = batch.account_id
    course_id = batch.course_id

    # ── Path A: brand-new user (or old account — create fresh sv-email account) ───
    if row.status in (
        RowStatus.VALID_NEW_USER,
        RowStatus.OLD_ACCOUNT_EXISTS,
        RowStatus.STALE_OLD_ACCOUNT,
    ):
        password = f"@{row.student_code}" if row.student_code else ""
        result = await _create_user_no_sis(
            token=token,
            base_url=base_url,
            account_id=account_id,
            full_name=row.full_name or "",
            email=row.generated_email or "",
            password=password,
        )
        if not result["success"]:
            err = result.get("error") or ""
            # Race: another import got there first → recover as existed_on_canvas
            if "đã tồn tại" in err.lower() or "taken" in err.lower():
                row.status = RowStatus.EXISTED_ON_CANVAS
                row.error_code = "race_existed_on_canvas"
                row.message = err
                # Fall through to Path B below by re-querying Canvas
            else:
                row.status = RowStatus.FAILED
                row.error_code = "create_user_failed"
                row.message = err[:500]
                await _audit(
                    db,
                    user_id=owner_id,
                    action=AuditAction.CREATE_USER,
                    canvas_domain=canvas_domain,
                    success=False,
                    detail={"row": row.row_number, "error": err},
                )
                return
        else:
            user = result["user"]
            row.canvas_user_id = int(user["id"])
            row.sis_user_id_used = None  # we intentionally do not send sis_user_id
            row.created_in_this_batch = True  # password "@<student_code>" is valid
            student = await sync_svc.upsert_canvas_student(
                db,
                canvas_domain=canvas_domain,
                owner_id=owner_id,
                canvas_user=user,
                source="excel_import",
                hint_student_code=row.student_code,
                hint_full_name=row.full_name,
            )
            row.canvas_student_id = student.id
            row.status = RowStatus.CREATED
            await _audit(
                db,
                user_id=owner_id,
                action=AuditAction.CREATE_USER,
                canvas_domain=canvas_domain,
                canvas_user_id=row.canvas_user_id,
                success=True,
                detail={"row": row.row_number, "via": "excel_import"},
            )

    # ── Path B: existed on Canvas — sync to DB (and optional enroll) ────
    if row.status == RowStatus.EXISTED_ON_CANVAS and row.canvas_student_id is None:
        # Re-resolve the user (preview did not write to DB for this case)
        match = await sync_svc.find_exact_canvas_user(
            token=token,
            base_url=base_url,
            account_id=account_id,
            student_code=row.student_code or "",
            generated_email=row.generated_email or "",
        )
        if match.status == "matched" and match.user is not None:
            student = await sync_svc.upsert_canvas_student(
                db,
                canvas_domain=canvas_domain,
                owner_id=owner_id,
                canvas_user=match.user,
                source="synced_from_canvas",
                hint_student_code=row.student_code,
                hint_full_name=row.full_name,
            )
            row.canvas_student_id = student.id
            row.canvas_user_id = student.canvas_user_id
        else:
            row.status = RowStatus.FAILED
            row.error_code = "canvas_user_disappeared"
            row.message = "User không còn match được trên Canvas khi confirm."
            return

    if row.status == RowStatus.EXISTED_IN_DB and row.canvas_user_id is None:
        # Should already be set in preview, but be defensive.
        local = await sync_svc.find_local_student(
            db,
            canvas_domain=canvas_domain,
            student_code=row.student_code,
            generated_email=row.generated_email,
        )
        if local is not None:
            row.canvas_user_id = local.canvas_user_id
            row.canvas_student_id = local.id

    # ── Optional enrollment after create / for existing ─────────────────
    needs_enroll = (
        course_id is not None
        and row.canvas_user_id is not None
        and (
            (row.status == RowStatus.CREATED and batch.enroll_after_create)
            or (
                row.status in (RowStatus.EXISTED_ON_CANVAS, RowStatus.EXISTED_IN_DB)
                and batch.enroll_existing
            )
        )
    )
    if not needs_enroll:
        return

    # Check current enrollment to avoid duplicates / illegal reactivation
    er = await canvas_service.list_user_enrollments_in_course(
        token, base_url, course_id, row.canvas_user_id  # type: ignore[arg-type]
    )
    enrollments = er.get("enrollments") or [] if er.get("success") else []
    state = _strongest_enrollment_state(enrollments)
    if state in ("active", "invited"):
        row.canvas_enrollment_id = _pick_enrollment_id(enrollments, state)
        # Don't downgrade status: a freshly-CREATED user that's somehow
        # already enrolled stays CREATED; an EXISTED row becomes ENROLLED-ish.
        if row.status != RowStatus.CREATED:
            row.status = RowStatus.ALREADY_ENROLLED
        return
    if state == "completed":
        # never reactivate per spec
        if row.status != RowStatus.CREATED:
            row.status = RowStatus.ENROLLMENT_COMPLETED
        return

    enroll_resp = await canvas_service.enroll_user(
        token, base_url, course_id, row.canvas_user_id  # type: ignore[arg-type]
    )
    if enroll_resp.get("success"):
        eid = enroll_resp.get("enrollment_id")
        row.canvas_enrollment_id = eid
        if row.status == RowStatus.CREATED:
            # keep CREATED status but record the enrollment id
            pass
        else:
            row.status = RowStatus.ENROLLED
        if row.canvas_student_id is not None and eid is not None:
            await sync_svc.upsert_enrollment(
                db,
                canvas_student_id=row.canvas_student_id,
                canvas_domain=canvas_domain,
                course_id=course_id,  # type: ignore[arg-type]
                enrollment=enroll_resp.get("enrollment") or {"id": eid, "enrollment_state": "active"},
            )
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.ENROLL_USER,
            canvas_domain=canvas_domain,
            canvas_course_id=course_id,
            canvas_user_id=row.canvas_user_id,
            success=True,
            detail={"row": row.row_number, "enrollment_id": eid},
        )
    else:
        row.status = RowStatus.ENROLLMENT_FAILED
        row.error_code = "enroll_failed"
        row.message = (enroll_resp.get("error") or "")[:500]
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.ENROLL_USER,
            canvas_domain=canvas_domain,
            canvas_course_id=course_id,
            canvas_user_id=row.canvas_user_id,
            success=False,
            detail={"row": row.row_number, "error": row.message},
        )


# ── Per-row confirm: ENROLL ───────────────────────────────────────────────

async def _confirm_enroll_row(
    db: AsyncSession,
    *,
    batch: StudentImportBatch,
    row: StudentImportRow,
    token: str,
    base_url: str,
    owner_id: uuid.UUID,
    reactivate_inactive: bool,
    recreate_deleted: bool,
) -> None:
    course_id = batch.course_id
    if course_id is None:
        row.status = RowStatus.FAILED
        row.error_code = ERR_NO_COURSE_FOR_ENROLL
        row.message = "Batch không có course_id."
        return

    canvas_domain = batch.canvas_domain

    # Status that don't need any Canvas action:
    if row.status in (
        RowStatus.INVALID,
        RowStatus.DUPLICATE_IN_FILE,
        RowStatus.USER_NOT_FOUND_ON_CANVAS,
        RowStatus.ALREADY_ENROLLED,
        RowStatus.ENROLLMENT_COMPLETED,  # never reactivate per spec
        RowStatus.FAILED,
    ):
        return

    if row.canvas_user_id is None:
        row.status = RowStatus.FAILED
        row.error_code = "missing_canvas_user_id"
        row.message = "Thiếu canvas_user_id sau preview."
        return

    if row.status == RowStatus.ENROLLMENT_INACTIVE and not reactivate_inactive:
        return
    if row.status == RowStatus.ENROLLMENT_DELETED and not recreate_deleted:
        return

    enroll_resp = await canvas_service.enroll_user(
        token, base_url, course_id, row.canvas_user_id
    )
    if enroll_resp.get("success"):
        eid = enroll_resp.get("enrollment_id")
        row.canvas_enrollment_id = eid
        row.status = RowStatus.ENROLLED
        if row.canvas_student_id is not None and eid is not None:
            await sync_svc.upsert_enrollment(
                db,
                canvas_student_id=row.canvas_student_id,
                canvas_domain=canvas_domain,
                course_id=course_id,
                enrollment=enroll_resp.get("enrollment") or {"id": eid, "enrollment_state": "active"},
            )
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.ENROLL_USER,
            canvas_domain=canvas_domain,
            canvas_course_id=course_id,
            canvas_user_id=row.canvas_user_id,
            success=True,
            detail={"row": row.row_number, "enrollment_id": eid, "from_status": row.status},
        )
    else:
        row.status = RowStatus.ENROLLMENT_FAILED
        row.error_code = "enroll_failed"
        row.message = (enroll_resp.get("error") or "")[:500]
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.ENROLL_USER,
            canvas_domain=canvas_domain,
            canvas_course_id=course_id,
            canvas_user_id=row.canvas_user_id,
            success=False,
            detail={"row": row.row_number, "error": row.message},
        )


# ── Internal: create-user with sis fallback ───────────────────────────────

async def _create_user_no_sis(
    *,
    token: str,
    base_url: str,
    account_id: int,
    full_name: str,
    email: str,
    password: str,
) -> dict:
    """
    Create a Canvas user with password, without sis_user_id.
    
    NEVER sends sis_user_id (avoids collision with old accounts that may
    already own the MSSV sis_user_id slot).  Password is set directly in
    the pseudonym so the student can log in immediately.
    """
    result = await canvas_service.create_canvas_user(
        token,
        base_url,
        account_id,
        name=full_name,
        email=email,
        sis_user_id=None,
        password=password,
    )
    return result


async def _create_user_with_sis_fallback(
    *,
    token: str,
    base_url: str,
    account_id: int,
    full_name: str,
    email: str,
    sis_user_id: Optional[str],
) -> dict:
    """
    Try with sis_user_id; if Canvas rejects it (400 + sis-related error),
    retry once without it.

    NEVER mutates the email (no '+sim<uuid>' retry).
    """
    first = await canvas_service.create_canvas_user(
        token,
        base_url,
        account_id,
        name=full_name,
        email=email,
        sis_user_id=sis_user_id,
    )
    if first.get("success") or not sis_user_id:
        if first.get("success"):
            first["sis_user_id_used"] = sis_user_id
        return first

    err_text = (first.get("error") or "").lower()
    looks_like_sis_problem = (
        "sis_user_id" in err_text
        or "sis id" in err_text
        or "sis user" in err_text
    )
    if not looks_like_sis_problem:
        return first

    logger.warning(
        "Canvas rejected sis_user_id=%r — retrying without it.", sis_user_id
    )
    second = await canvas_service.create_canvas_user(
        token,
        base_url,
        account_id,
        name=full_name,
        email=email,
        sis_user_id=None,
    )
    if second.get("success"):
        second["sis_user_id_used"] = None
    return second


# ── Read helpers ──────────────────────────────────────────────────────────

async def get_batch(
    db: AsyncSession,
    *,
    batch_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> StudentImportBatch:
    stmt = (
        select(StudentImportBatch)
        .where(StudentImportBatch.id == batch_id)
        .options(selectinload(StudentImportBatch.rows))
    )
    batch = (await db.execute(stmt)).scalar_one_or_none()
    if batch is None:
        raise BatchNotFoundError(ERR_BATCH_NOT_FOUND)
    if batch.owner_id != owner_id:
        raise BatchForbiddenError(ERR_BATCH_FORBIDDEN)
    return batch
