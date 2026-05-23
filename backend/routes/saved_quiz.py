"""
Saved Quiz API Routes
=====================
CRUD endpoints for snapshot-based saved quizzes.
All endpoints are scoped to the authenticated user.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import CurrentUser
from backend.database.base import get_async_session
from backend.database.models.user import User
from backend.schemas import (
    SavedQuizCreate,
    SavedQuizUpdate,
    SavedQuizQuestionCreate,
    SavedQuizOut,
    SavedQuizDetailOut,
    SavedQuizListOut,
    SavedQuizQuestionOut,
    CourseGroupOut,
)
from backend.services.saved_quiz_service import SavedQuizService

logger = logging.getLogger(__name__)

router = APIRouter()


def _service(db: AsyncSession) -> SavedQuizService:
    return SavedQuizService(db)


# ─── Create ──────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=SavedQuizDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save a new quiz snapshot",
)
async def create_saved_quiz(
    body: SavedQuizCreate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    quiz = await svc.create_quiz(user.id, body)
    return quiz


# ─── List (paginated + filtered) ────────────────────────────────────────────

@router.get(
    "/",
    response_model=SavedQuizListOut,
    summary="List saved quizzes with filters",
)
async def list_saved_quizzes(
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    course_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    difficulty: Optional[str] = Query(None),
    starred: Optional[bool] = Query(None),
    sort: str = Query("newest", regex="^(newest|oldest|title|questions)$"),
):
    svc = _service(db)
    quizzes, total = await svc.list_quizzes(
        user.id,
        page=page,
        page_size=page_size,
        course_id=course_id,
        search=search,
        difficulty=difficulty,
        starred=starred,
        sort=sort,
    )
    courses = await svc.get_course_groups(user.id)
    return SavedQuizListOut(
        items=quizzes,
        total=total,
        page=page,
        page_size=page_size,
        courses=courses,
    )


# ─── Course groups ───────────────────────────────────────────────────────────

@router.get(
    "/courses",
    response_model=list[CourseGroupOut],
    summary="Get courses that have saved quizzes",
)
async def get_course_groups(
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    return await svc.get_course_groups(user.id)


# ─── Detail ──────────────────────────────────────────────────────────────────

@router.get(
    "/{quiz_id}",
    response_model=SavedQuizDetailOut,
    summary="Get saved quiz with all questions",
)
async def get_saved_quiz(
    quiz_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    quiz = await svc.get_quiz(quiz_id, user.id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


# ─── Update metadata ────────────────────────────────────────────────────────

@router.put(
    "/{quiz_id}",
    response_model=SavedQuizOut,
    summary="Update quiz metadata",
)
async def update_saved_quiz(
    quiz_id: UUID,
    body: SavedQuizUpdate,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    quiz = await svc.update_quiz(quiz_id, user.id, body)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


# ─── Delete ──────────────────────────────────────────────────────────────────

@router.delete(
    "/{quiz_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a saved quiz",
)
async def delete_saved_quiz(
    quiz_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    deleted = await svc.delete_quiz(quiz_id, user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return {"success": True, "detail": "Quiz deleted"}


# ─── Toggle star ─────────────────────────────────────────────────────────────

@router.patch(
    "/{quiz_id}/star",
    response_model=SavedQuizOut,
    summary="Toggle starred status",
)
async def toggle_star(
    quiz_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    quiz = await svc.toggle_star(quiz_id, user.id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


# ─── Duplicate ───────────────────────────────────────────────────────────────

@router.post(
    "/{quiz_id}/duplicate",
    response_model=SavedQuizDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="Duplicate a quiz (deep copy)",
)
async def duplicate_saved_quiz(
    quiz_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    svc = _service(db)
    quiz = await svc.duplicate_quiz(quiz_id, user.id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


# ─── Bulk replace questions ──────────────────────────────────────────────────

@router.put(
    "/{quiz_id}/questions",
    response_model=SavedQuizDetailOut,
    summary="Replace all questions in a quiz",
)
async def replace_questions(
    quiz_id: UUID,
    questions: list[SavedQuizQuestionCreate],
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one question is required",
        )
    svc = _service(db)
    quiz = await svc.replace_questions(quiz_id, user.id, questions)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz
