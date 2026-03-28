"""
Canvas Results Aggregation Routes
=================================
Endpoints for the Results Aggregation panel:
  - Quiz submission results + statistics
  - Course enrollment grades + statistics
  - CSV export
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from backend.auth.dependencies import CurrentUser
from backend.services import canvas_results_service as results_svc
from backend.services.canvas_connection import resolve_canvas_connection_async

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/quiz/{course_id}/{quiz_id}")
async def quiz_results(
    course_id: int,
    quiz_id: int,
    http_request: Request,
    _user: CurrentUser,
):
    """Fetch and aggregate quiz submission results."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
    data = await results_svc.get_quiz_results(token, base_url, course_id, quiz_id)
    if not data.get("success"):
        raise HTTPException(status_code=400, detail=data.get("error", "Failed to fetch quiz results"))
    return data


@router.get("/course/{course_id}/grades")
async def course_grades(
    course_id: int,
    http_request: Request,
    _user: CurrentUser,
):
    """Fetch and aggregate enrollment grades for a course."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
    data = await results_svc.get_course_grades(token, base_url, course_id)
    if not data.get("success"):
        raise HTTPException(status_code=400, detail=data.get("error", "Failed to fetch course grades"))
    return data


@router.get("/export/quiz/{course_id}/{quiz_id}")
async def export_quiz_csv(
    course_id: int,
    quiz_id: int,
    http_request: Request,
    _user: CurrentUser,
):
    """Export quiz results as CSV."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
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
    http_request: Request,
    _user: CurrentUser,
):
    """Export quiz results as Excel (.xlsx)."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
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
    http_request: Request,
    _user: CurrentUser,
):
    """Export course grades as CSV."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
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
    http_request: Request,
    _user: CurrentUser,
):
    """Export course grades as Excel (.xlsx)."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=_user.id,
        request=http_request,
    )
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
