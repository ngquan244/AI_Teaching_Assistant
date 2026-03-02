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

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.auth.dependencies import CurrentUser
from backend.database.base import get_db
from backend.schemas import (
    SimulationExecuteRequest,
    SimulationBatchRequest,
    SimulationPreCheckResponse,
    TestStudentCreate,
    TestStudentOut,
    SimulationRunOut,
)
from backend.services import canvas_simulation_service as sim_svc

from sqlalchemy.ext.asyncio import AsyncSession

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
# Pre-Check
# ============================================================================

@router.get("/pre-check/{course_id}/{quiz_id}", response_model=SimulationPreCheckResponse)
async def pre_check(
    course_id: int,
    quiz_id: int,
    _user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
):
    """Validate quiz readiness before simulation."""
    token, base_url = creds
    result = await sim_svc.pre_check_quiz(token, base_url, course_id, quiz_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "Pre-check failed"))
    return result


# ============================================================================
# Test Students
# ============================================================================

@router.post("/test-students", status_code=201)
async def create_test_student(
    body: TestStudentCreate,
    user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Create a new test student on Canvas."""
    token, base_url = creds
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
    db: AsyncSession = Depends(get_db),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """List all test students belonging to the current user."""
    domain = x_canvas_base_url or None
    students = await sim_svc.list_test_students(db, user.id, canvas_domain=domain)
    return {"success": True, "test_students": students, "total": len(students)}


@router.delete("/test-students/{test_student_id}")
async def delete_test_student(
    test_student_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """Delete a test student — unenroll + delete on Canvas + soft-delete locally."""
    if not x_canvas_token or not x_canvas_base_url:
        raise HTTPException(status_code=400, detail="Canvas token and base URL required")
    result = await sim_svc.delete_test_student(
        db, x_canvas_token, x_canvas_base_url,
        owner_id=user.id,
        test_student_id=test_student_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


# ============================================================================
# Execute Simulation
# ============================================================================

@router.post("/execute")
async def execute_simulation(
    body: SimulationExecuteRequest,
    user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Execute a single simulation attempt."""
    token, base_url = creds
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
    user: CurrentUser,
    creds: tuple[str, str] = Depends(get_canvas_credentials),
    db: AsyncSession = Depends(get_db),
):
    """Execute multiple simulation attempts with different answer sets."""
    token, base_url = creds
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


# ============================================================================
# History & Audit
# ============================================================================

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
