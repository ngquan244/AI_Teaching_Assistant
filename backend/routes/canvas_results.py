"""
Canvas Results Aggregation Routes
=================================
Endpoints for the Results Aggregation panel:
  - Quiz submission results + statistics
  - Course enrollment grades + statistics
  - CSV export
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse, Response

from backend.auth.dependencies import CurrentUser
from backend.services import canvas_results_service as results_svc

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Helper
# ============================================================================

def get_canvas_credentials(
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
) -> tuple[str, str]:
    if not x_canvas_token:
        raise HTTPException(status_code=401, detail="Canvas access token not provided")
    base_url = x_canvas_base_url or "https://lms.uet.vnu.edu.vn"
    return x_canvas_token, base_url


# ============================================================================
# Quiz Results
# ============================================================================

@router.get("/quiz/{course_id}/{quiz_id}")
async def quiz_results(
    course_id: int,
    quiz_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Fetch and aggregate quiz submission results."""
    token, base_url = creds
    data = await results_svc.get_quiz_results(token, base_url, course_id, quiz_id)
    if not data.get("success"):
        raise HTTPException(status_code=400, detail=data.get("error", "Failed to fetch quiz results"))
    return data


# ============================================================================
# Course Grades
# ============================================================================

@router.get("/course/{course_id}/grades")
async def course_grades(
    course_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Fetch and aggregate enrollment grades for a course."""
    token, base_url = creds
    data = await results_svc.get_course_grades(token, base_url, course_id)
    if not data.get("success"):
        raise HTTPException(status_code=400, detail=data.get("error", "Failed to fetch course grades"))
    return data


# ============================================================================
# Export
# ============================================================================

@router.get("/export/quiz/{course_id}/{quiz_id}")
async def export_quiz_csv(
    course_id: int,
    quiz_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Export quiz results as CSV."""
    token, base_url = creds
    try:
        csv_content, filename = await results_svc.export_quiz_results_csv(
            token, base_url, course_id, quiz_id
        )
    except ValueError as e:
        logger.warning("Invalid quiz export request: %s", e)
        raise HTTPException(status_code=400, detail="Dữ liệu đầu vào không hợp lệ")

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/quiz/{course_id}/{quiz_id}/excel")
async def export_quiz_excel(
    course_id: int,
    quiz_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Export quiz results as Excel (.xlsx)."""
    token, base_url = creds
    try:
        xlsx_bytes, filename = await results_svc.export_quiz_results_excel(
            token, base_url, course_id, quiz_id
        )
    except ValueError as e:
        logger.warning("Invalid quiz excel export request: %s", e)
        raise HTTPException(status_code=400, detail="Dữ liệu đầu vào không hợp lệ")

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/course/{course_id}")
async def export_course_csv(
    course_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Export course grades as CSV."""
    token, base_url = creds
    try:
        csv_content, filename = await results_svc.export_course_grades_csv(
            token, base_url, course_id
        )
    except ValueError as e:
        logger.warning("Invalid course export request: %s", e)
        raise HTTPException(status_code=400, detail="Dữ liệu đầu vào không hợp lệ")

    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/course/{course_id}/excel")
async def export_course_excel(
    course_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Export course grades as Excel (.xlsx)."""
    token, base_url = creds
    try:
        xlsx_bytes, filename = await results_svc.export_course_grades_excel(
            token, base_url, course_id
        )
    except ValueError as e:
        logger.warning("Invalid course excel export request: %s", e)
        raise HTTPException(status_code=400, detail="Dữ liệu đầu vào không hợp lệ")

    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
