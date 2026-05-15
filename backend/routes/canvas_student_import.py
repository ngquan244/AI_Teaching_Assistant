"""
Canvas Student Import Routes
============================

POST   /preview          — multipart upload, returns the preview batch
POST   /confirm          — body includes batch_id + toggles, executes mutations
GET    /batches/{id}     — re-fetch a batch (for polling / refresh)
GET    /template.xlsx    — runtime-built blank template

Mounted at ``/api/canvas/students/import`` from ``backend/main.py``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import CurrentUser
from backend.database.base import get_db
from backend.database.models import (
    StudentImportBatch,
    StudentImportRow,
)
from backend.services import canvas_student_import_service as import_svc
from backend.services.canvas_connection import resolve_canvas_connection_async
from backend.utils.excel_student_parser import build_template_xlsx

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────

class ImportRowOut(BaseModel):
    id: UUID
    row_number: int
    student_code: Optional[str] = None
    full_name: Optional[str] = None
    generated_email: Optional[str] = None
    status: str
    canvas_user_id: Optional[int] = None
    canvas_enrollment_id: Optional[int] = None
    canvas_student_id: Optional[UUID] = None
    sis_user_id_used: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    created_in_this_batch: bool = False
    initial_password: Optional[str] = None  # set iff created_in_this_batch; not stored in DB


class ImportBatchOut(BaseModel):
    id: UUID
    owner_id: UUID
    canvas_domain: str
    account_id: int
    course_id: Optional[int] = None
    mode: str
    filename: Optional[str] = None
    status: str
    total_rows: int
    summary: Optional[dict] = None
    enroll_after_create: bool
    enroll_existing: bool
    expires_at: Optional[str] = None
    created_at: Optional[str] = None
    confirmed_at: Optional[str] = None
    rows: list[ImportRowOut] = Field(default_factory=list)


def _serialize_batch(
    batch: StudentImportBatch,
    rows: list[StudentImportRow],
) -> ImportBatchOut:
    return ImportBatchOut(
        id=batch.id,
        owner_id=batch.owner_id,
        canvas_domain=batch.canvas_domain,
        account_id=batch.account_id,
        course_id=batch.course_id,
        mode=batch.mode,
        filename=batch.filename,
        status=batch.status,
        total_rows=batch.total_rows,
        summary=batch.summary,
        enroll_after_create=batch.enroll_after_create,
        enroll_existing=batch.enroll_existing,
        expires_at=batch.expires_at.isoformat() if batch.expires_at else None,
        created_at=batch.created_at.isoformat() if batch.created_at else None,
        confirmed_at=batch.confirmed_at.isoformat() if batch.confirmed_at else None,
        rows=[
            ImportRowOut(
                id=r.id,
                row_number=r.row_number,
                student_code=r.student_code,
                full_name=r.full_name,
                generated_email=r.generated_email,
                status=r.status,
                canvas_user_id=r.canvas_user_id,
                canvas_enrollment_id=r.canvas_enrollment_id,
                canvas_student_id=r.canvas_student_id,
                sis_user_id_used=r.sis_user_id_used,
                error_code=r.error_code,
                message=r.message,
                created_in_this_batch=r.created_in_this_batch,
                initial_password=(
                    f"@{r.student_code}"
                    if r.created_in_this_batch and r.student_code
                    else None
                ),
            )
            for r in rows
        ],
    )


async def _load_batch_rows(
    db: AsyncSession, batch_id: UUID
) -> list[StudentImportRow]:
    """Eager-load rows for a batch in async-safe way, ordered by row_number."""
    result = await db.execute(
        select(StudentImportRow)
        .where(StudentImportRow.batch_id == batch_id)
        .order_by(StudentImportRow.row_number.asc())
    )
    return list(result.scalars().all())


# ── Request schemas ───────────────────────────────────────────────────────

class ConfirmRequest(BaseModel):
    batch_id: UUID
    enroll_after_create: Optional[bool] = None
    enroll_existing: Optional[bool] = None
    reactivate_inactive: bool = False
    recreate_deleted: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


@router.post("/preview", response_model=ImportBatchOut)
async def preview(
    http_request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
    mode: str = Form(...),
    account_id: int = Form(1),
    course_id: Optional[int] = Form(None),
    enroll_after_create: bool = Form(False),
    enroll_existing: bool = Form(False),
    canvas_domain_hint: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Upload an Excel file and receive a classified preview batch."""
    if mode not in ("create", "enroll"):
        raise HTTPException(status_code=400, detail="mode must be 'create' or 'enroll'")
    if mode == "enroll" and not course_id:
        raise HTTPException(
            status_code=400, detail="course_id is required when mode='enroll'"
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="File rỗng.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File lớn hơn 5 MB.")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400, detail="Chỉ hỗ trợ định dạng .xlsx ở phase này."
        )

    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
        canvas_domain_hint=canvas_domain_hint,
    )

    try:
        batch = await import_svc.preview_import(
            db,
            owner_id=user.id,
            file_bytes=raw,
            filename=file.filename or "upload.xlsx",
            mode=mode,
            canvas_domain=base_url,
            account_id=account_id,
            course_id=course_id,
            enroll_after_create=enroll_after_create,
            enroll_existing=enroll_existing,
            token=token,
            base_url=base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rows = await _load_batch_rows(db, batch.id)
    return _serialize_batch(batch, rows)


@router.post("/confirm", response_model=ImportBatchOut)
async def confirm(
    body: ConfirmRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Execute Canvas mutations for a previously-previewed batch."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )

    try:
        batch = await import_svc.confirm_import(
            db,
            owner_id=user.id,
            batch_id=body.batch_id,
            token=token,
            base_url=base_url,
            enroll_after_create=body.enroll_after_create,
            enroll_existing=body.enroll_existing,
            reactivate_inactive=body.reactivate_inactive,
            recreate_deleted=body.recreate_deleted,
        )
    except import_svc.ConfirmAlreadyDoneError as exc:
        # Idempotent: return the existing batch with an explicit error_code
        # so the client can show a "đã confirm rồi" notice.
        existing_rows = await _load_batch_rows(db, exc.batch.id)
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": import_svc.ERR_BATCH_ALREADY_CONFIRMED,
                "batch": _serialize_batch(exc.batch, existing_rows).model_dump(
                    mode="json"
                ),
            },
        ) from exc
    except import_svc.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except import_svc.BatchForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except import_svc.BatchInvalidStateError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": import_svc.ERR_BATCH_INVALID_STATE,
                "status": exc.status,
            },
        ) from exc

    rows = await _load_batch_rows(db, batch.id)
    return _serialize_batch(batch, rows)


@router.get("/batches/{batch_id}", response_model=ImportBatchOut)
async def get_batch(
    batch_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    try:
        batch = await import_svc.get_batch(db, batch_id=batch_id, owner_id=user.id)
    except import_svc.BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except import_svc.BatchForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    rows = await _load_batch_rows(db, batch.id)
    return _serialize_batch(batch, rows)


@router.get("/template.xlsx")
async def download_template(user: CurrentUser):
    """Runtime-built blank template (no static file on disk)."""
    payload = build_template_xlsx()
    return Response(
        content=payload,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="student_import_template.xlsx"'
            ),
        },
    )
