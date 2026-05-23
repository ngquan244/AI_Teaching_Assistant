"""
SavedQuiz Service
=================
Business logic for CRUD operations on snapshot-based saved quizzes.
All queries are scoped to the requesting user.
"""
import logging
import uuid
from typing import Optional, List, Tuple

from sqlalchemy import select, func, delete, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models.saved_quiz import SavedQuiz, SavedQuizQuestion
from backend.schemas import (
    SavedQuizCreate,
    SavedQuizUpdate,
    SavedQuizQuestionCreate,
    CourseGroupOut,
)

logger = logging.getLogger(__name__)


class SavedQuizService:
    """Service for managing saved quiz snapshots."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Create
    # =========================================================================

    async def create_quiz(
        self, user_id: uuid.UUID, data: SavedQuizCreate
    ) -> SavedQuiz:
        """Create a new saved quiz with questions (snapshot)."""
        quiz = SavedQuiz(
            user_id=user_id,
            title=data.title,
            course_id=data.course_id,
            course_name=data.course_name,
            description=data.description,
            difficulty=data.difficulty,
            language=data.language,
            source=data.source,
            source_job_id=data.source_job_id,
            tags=data.tags,
            question_count=len(data.questions),
            is_starred=False,
        )

        # Attach questions
        for idx, q in enumerate(data.questions, start=1):
            quiz.questions.append(
                SavedQuizQuestion(
                    question_number=idx,
                    question_text=q.question_text,
                    options=q.options,
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    question_type=q.question_type,
                    points=q.points,
                )
            )

        self.db.add(quiz)
        await self.db.flush()
        return quiz

    # =========================================================================
    # Read — single
    # =========================================================================

    async def get_quiz(
        self, quiz_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[SavedQuiz]:
        """Get a single quiz with questions, scoped to user."""
        stmt = (
            select(SavedQuiz)
            .options(selectinload(SavedQuiz.questions))
            .where(SavedQuiz.id == quiz_id, SavedQuiz.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # =========================================================================
    # Read — list (paginated + filtered)
    # =========================================================================

    async def list_quizzes(
        self,
        user_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 12,
        course_id: Optional[int] = None,
        search: Optional[str] = None,
        difficulty: Optional[str] = None,
        starred: Optional[bool] = None,
        sort: str = "newest",
    ) -> Tuple[List[SavedQuiz], int]:
        """Return paginated quizzes for a user with optional filters."""
        base = select(SavedQuiz).where(SavedQuiz.user_id == user_id)

        # Filters
        if course_id is not None:
            base = base.where(SavedQuiz.course_id == course_id)
        if search:
            pattern = f"%{search}%"
            base = base.where(SavedQuiz.title.ilike(pattern))
        if difficulty:
            base = base.where(SavedQuiz.difficulty == difficulty)
        if starred is not None:
            base = base.where(SavedQuiz.is_starred == starred)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = await self.db.scalar(count_stmt) or 0

        # Sort
        if sort == "oldest":
            base = base.order_by(SavedQuiz.created_at.asc())
        elif sort == "title":
            base = base.order_by(SavedQuiz.title.asc())
        elif sort == "questions":
            base = base.order_by(SavedQuiz.question_count.desc())
        else:  # newest (default)
            base = base.order_by(SavedQuiz.created_at.desc())

        # Paginate
        offset = (page - 1) * page_size
        stmt = base.offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        quizzes = list(result.scalars().all())

        return quizzes, total

    # =========================================================================
    # Course groups (for sidebar)
    # =========================================================================

    async def get_course_groups(
        self, user_id: uuid.UUID
    ) -> List[CourseGroupOut]:
        """Get distinct courses with quiz counts for this user."""
        stmt = (
            select(
                SavedQuiz.course_id,
                SavedQuiz.course_name,
                func.count(SavedQuiz.id).label("quiz_count"),
            )
            .where(SavedQuiz.user_id == user_id)
            .group_by(SavedQuiz.course_id, SavedQuiz.course_name)
            .order_by(func.count(SavedQuiz.id).desc())
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            CourseGroupOut(
                course_id=row.course_id,
                course_name=row.course_name,
                quiz_count=row.quiz_count,
            )
            for row in rows
        ]

    # =========================================================================
    # Update — metadata
    # =========================================================================

    async def update_quiz(
        self,
        quiz_id: uuid.UUID,
        user_id: uuid.UUID,
        data: SavedQuizUpdate,
    ) -> Optional[SavedQuiz]:
        """Update quiz metadata fields."""
        quiz = await self.get_quiz(quiz_id, user_id)
        if quiz is None:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(quiz, field, value)

        await self.db.flush()
        return quiz

    # =========================================================================
    # Toggle star
    # =========================================================================

    async def toggle_star(
        self, quiz_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[SavedQuiz]:
        """Toggle the is_starred flag."""
        quiz = await self.get_quiz(quiz_id, user_id)
        if quiz is None:
            return None

        quiz.is_starred = not quiz.is_starred
        await self.db.flush()
        return quiz

    # =========================================================================
    # Duplicate (deep copy)
    # =========================================================================

    async def duplicate_quiz(
        self, quiz_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[SavedQuiz]:
        """Deep-copy a quiz and all its questions."""
        original = await self.get_quiz(quiz_id, user_id)
        if original is None:
            return None

        copy = SavedQuiz(
            user_id=user_id,
            title=f"{original.title} (copy)",
            course_id=original.course_id,
            course_name=original.course_name,
            description=original.description,
            difficulty=original.difficulty,
            language=original.language,
            source=original.source,
            tags=list(original.tags),
            question_count=original.question_count,
            is_starred=False,
        )
        for q in original.questions:
            copy.questions.append(
                SavedQuizQuestion(
                    question_number=q.question_number,
                    question_text=q.question_text,
                    options=dict(q.options),
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    question_type=q.question_type,
                    points=q.points,
                )
            )

        self.db.add(copy)
        await self.db.flush()
        return copy

    # =========================================================================
    # Bulk replace questions
    # =========================================================================

    async def replace_questions(
        self,
        quiz_id: uuid.UUID,
        user_id: uuid.UUID,
        questions: List[SavedQuizQuestionCreate],
    ) -> Optional[SavedQuiz]:
        """Replace all questions in a quiz (bulk update)."""
        quiz = await self.get_quiz(quiz_id, user_id)
        if quiz is None:
            return None

        # Delete existing questions
        await self.db.execute(
            delete(SavedQuizQuestion).where(
                SavedQuizQuestion.quiz_id == quiz_id
            )
        )

        # Insert new questions
        new_questions = []
        for idx, q in enumerate(questions, start=1):
            new_questions.append(
                SavedQuizQuestion(
                    quiz_id=quiz_id,
                    question_number=idx,
                    question_text=q.question_text,
                    options=q.options,
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    question_type=q.question_type,
                    points=q.points,
                )
            )
        self.db.add_all(new_questions)

        # Update denormalised count
        quiz.question_count = len(questions)
        await self.db.flush()

        # Refresh to load new questions
        await self.db.refresh(quiz)
        return quiz

    # =========================================================================
    # Delete
    # =========================================================================

    async def delete_quiz(
        self, quiz_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        """Delete a quiz and all its questions (cascade)."""
        quiz = await self.get_quiz(quiz_id, user_id)
        if quiz is None:
            return False

        await self.db.delete(quiz)
        await self.db.flush()
        return True
