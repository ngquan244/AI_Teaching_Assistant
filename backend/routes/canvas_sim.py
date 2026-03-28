"""
Canvas Simulation Routes
========================
Endpoints for the Attempt Simulation panel:
  - Pre-check quiz readiness
  - CRUD test students
  - Execute single / batch simulations
  - View simulation history & audit log
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import CurrentUser
from backend.database.base import get_db
from backend.schemas import (
    SimulationExecuteRequest,
    SimulationBatchRequest,
    SimulationPreCheckResponse,
    TestStudentCreate,
)
from backend.services import canvas_simulation_service as sim_svc
from backend.services.canvas_connection import resolve_canvas_connection_async

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/pre-check/{course_id}/{quiz_id}", response_model=SimulationPreCheckResponse)
async def pre_check(
    course_id: int,
    quiz_id: int,
    http_request: Request,
    user: CurrentUser,
):
    """Validate quiz readiness before simulation."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    result = await sim_svc.pre_check_quiz(token, base_url, course_id, quiz_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Pre-check failed"))
    return result


@router.post("/test-students", status_code=201)
async def create_test_student(
    body: TestStudentCreate,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Create a new test student on Canvas."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    result = await sim_svc.create_test_student(
        db, token, base_url,
        owner_id=user.id,
        name=body.name,
        email=body.email,
        account_id=body.account_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to create test student"))
    return result


@router.get("/test-students")
async def list_test_students(
    user: CurrentUser,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """List all test students belonging to the current user."""
    _, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
        require=False,
    )
    students = await sim_svc.list_test_students(db, user.id, canvas_domain=base_url)
    return {"success": True, "test_students": students, "total": len(students)}


@router.delete("/test-students/{test_student_id}")
async def delete_test_student(
    test_student_id: str,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Delete a test student: unenroll + delete on Canvas + soft-delete locally."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    result = await sim_svc.delete_test_student(
        db, token, base_url,
        owner_id=user.id,
        test_student_id=test_student_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/execute")
async def execute_simulation(
    body: SimulationExecuteRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Execute a single simulation attempt."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    answers = [{"question_id": a.question_id, "answer": a.answer} for a in body.answers]
    result = await sim_svc.execute_simulation(
        db, token, base_url,
        owner_id=user.id,
        course_id=body.course_id,
        quiz_id=body.quiz_id,
        test_student_id=body.test_student_id,
        answers=answers,
        access_code=body.access_code,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Simulation failed"))
    return result


@router.post("/execute-batch")
async def execute_batch_simulation(
    body: SimulationBatchRequest,
    http_request: Request,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Execute multiple simulation attempts with different answer sets."""
    token, base_url = await resolve_canvas_connection_async(
        user_id=user.id,
        request=http_request,
    )
    answer_sets = [
        [{"question_id": a.question_id, "answer": a.answer} for a in ans_list]
        for ans_list in body.answer_sets
    ]
    result = await sim_svc.execute_batch_simulation(
        db, token, base_url,
        owner_id=user.id,
        course_id=body.course_id,
        quiz_id=body.quiz_id,
        test_student_id=body.test_student_id,
        answer_sets=answer_sets,
        access_code=body.access_code,
    )
    return result


@router.get("/history")
async def simulation_history(
    user: CurrentUser,
    course_id: Optional[int] = None,
    quiz_id: Optional[int] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Get simulation run history."""
    runs = await sim_svc.list_simulation_runs(
        db, user.id, course_id=course_id, quiz_id=quiz_id, limit=limit
    )
    return {"success": True, "runs": runs, "total": len(runs)}


@router.get("/audit-log")
async def audit_log(
    user: CurrentUser,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    """Get audit log for the current user's simulation activities."""
    logs = await sim_svc.list_audit_logs(db, user.id, limit=limit)
    return {"success": True, "logs": logs, "total": len(logs)}
