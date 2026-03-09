"""
Canvas Quiz API Routes
======================
Endpoints for creating quizzes on Canvas LMS via API.
Supports two question sources:
  - direct questions (from AI generation / QTI flow)
  - questions copied from existing Canvas quizzes
"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from backend.auth.dependencies import CurrentUser
from backend.schemas import (
    CreateCanvasQuizRequest,
    CreateCanvasQuizResponse,
)
from backend.services.canvas_service import (
    list_quizzes,
    list_quiz_questions,
    build_full_quiz,
    list_question_banks,
    list_bank_questions,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# Helper — reuse same pattern as canvas.py
# ============================================================================

def get_canvas_credentials(
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
) -> tuple[str, str]:
    """Extract Canvas credentials from headers."""
    if not x_canvas_token:
        raise HTTPException(
            status_code=401,
            detail="Canvas access token not provided",
        )
    base_url = x_canvas_base_url or "https://lms.uet.vnu.edu.vn"
    return x_canvas_token, base_url


# ============================================================================
# Quizzes & Questions
# ============================================================================

@router.get("/courses/{course_id}/quizzes")
async def get_quizzes(
    course_id: int,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """List existing quizzes for a course."""
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    result = await list_quizzes(token, base_url, course_id)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed"))
    return result


@router.get("/courses/{course_id}/quizzes/{quiz_id}/questions")
async def get_quiz_questions(
    course_id: int,
    quiz_id: int,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """List all questions in an existing quiz (paginated)."""
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    result = await list_quiz_questions(token, base_url, course_id, quiz_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "Failed"))
    return result


# ============================================================================
# Question Banks
# ============================================================================

@router.get("/courses/{course_id}/question-banks")
async def get_question_banks(
    course_id: int,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """List assessment question banks for a course."""
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    result = await list_question_banks(token, base_url, course_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "Failed"))
    return result


@router.get("/courses/{course_id}/question-banks/{bank_id}/questions")
async def get_bank_questions(
    course_id: int,
    bank_id: int,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """List questions in an assessment question bank."""
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)
    result = await list_bank_questions(token, base_url, course_id, bank_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error", "Failed"))
    return result


# ============================================================================
# Create Quiz (end-to-end)
# ============================================================================

@router.post("/create-quiz", response_model=CreateCanvasQuizResponse)
async def create_full_quiz(
    request: CreateCanvasQuizRequest,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None, alias="X-Canvas-Token"),
    x_canvas_base_url: Optional[str] = Header(None, alias="X-Canvas-Base-Url"),
):
    """
    Create a full Canvas quiz:
    1. Create quiz shell with settings
    2. Add direct questions (from AI generation)
    3. Copy questions from source quizzes (optional)
    4. Optionally publish
    """
    token, base_url = get_canvas_credentials(x_canvas_token, x_canvas_base_url)

    quiz_params = request.quiz.model_dump(exclude_none=True)
    direct_questions = [dq.model_dump() for dq in request.direct_questions]
    source_questions = [sq.model_dump() for sq in request.source_questions]

    result = await build_full_quiz(
        token=token,
        base_url=base_url,
        course_id=request.course_id,
        quiz_params=quiz_params,
        direct_questions=direct_questions,
        source_questions=source_questions,
        default_points=request.default_points,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "Failed"))

    return CreateCanvasQuizResponse(
        success=True,
        quiz_id=result.get("quiz_id"),
        quiz_url=result.get("quiz_url"),
        title=result.get("title"),
        questions_added=result.get("questions_added", 0),
        groups_created=0,
        message=result.get("message"),
    )
