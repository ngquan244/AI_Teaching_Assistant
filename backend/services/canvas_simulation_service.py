"""
Canvas Simulation Service
=========================
Orchestrates the full "attempt simulation" lifecycle:

1. Pre-check: verify quiz is published, course is published, etc.
2. Test-student CRUD: create / list / delete test-student accounts on Canvas.
3. Execute: enroll → start submission → answer → complete → record result.
4. Audit: every Canvas mutation is logged.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models.canvas_simulation import (
    AuditAction,
    CanvasAuditLog,
    SimulationRun,
    SimulationStatus,
    TestStudent,
    TestStudentStatus,
)
from backend.services import canvas_service

logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

async def _audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    action: AuditAction,
    canvas_domain: str,
    success: bool,
    simulation_run_id: uuid.UUID | None = None,
    canvas_course_id: int | None = None,
    canvas_user_id: int | None = None,
    canvas_quiz_id: int | None = None,
    canvas_submission_id: int | None = None,
    detail: str | None = None,
) -> None:
    """Append an immutable audit-log entry."""
    entry = CanvasAuditLog(
        user_id=user_id,
        action=action,
        simulation_run_id=simulation_run_id,
        canvas_domain=canvas_domain,
        canvas_course_id=canvas_course_id,
        canvas_user_id=canvas_user_id,
        canvas_quiz_id=canvas_quiz_id,
        canvas_submission_id=canvas_submission_id,
        success=success,
        detail=detail,
    )
    db.add(entry)
    # Don't commit here — let the caller handle the transaction.


# ============================================================================
# Pre-Check
# ============================================================================

async def pre_check_quiz(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
) -> dict:
    """
    Validate that a quiz is ready for simulation.
    Returns warnings / blockers (IP filter, access code, unpublished, etc.).
    """
    warnings: list[str] = []

    # 1. Fetch quiz details
    quizzes_result = await canvas_service.list_quizzes(token, base_url, course_id)
    if not quizzes_result["success"]:
        return {"success": False, "error": "Cannot fetch quizzes: " + quizzes_result.get("error", "")}

    quiz = None
    for q in quizzes_result.get("quizzes", []):
        if q.get("id") == quiz_id:
            quiz = q
            break

    if quiz is None:
        return {"success": False, "error": f"Quiz {quiz_id} not found in course {course_id}"}

    quiz_published = quiz.get("published", False)
    if not quiz_published:
        warnings.append("Quiz is NOT published — students cannot take it.")

    quiz_type = quiz.get("quiz_type", "assignment")
    allowed_attempts = quiz.get("allowed_attempts", 1)
    ip_filter = quiz.get("ip_filter")
    access_code = quiz.get("access_code")

    if ip_filter:
        warnings.append(f"Quiz has IP filter: {ip_filter}. The simulation server IP must match.")

    access_code_required = bool(access_code)
    if access_code_required:
        warnings.append("Quiz requires an access code.")

    return {
        "success": True,
        "course_published": True,  # If we can list quizzes, the course is accessible
        "quiz_published": quiz_published,
        "quiz_type": quiz_type,
        "allowed_attempts": allowed_attempts,
        "ip_filter": ip_filter,
        "access_code_required": access_code_required,
        "warnings": warnings,
    }


# ============================================================================
# Test-Student CRUD
# ============================================================================

async def create_test_student(
    db: AsyncSession,
    token: str,
    base_url: str,
    *,
    owner_id: uuid.UUID,
    name: str,
    email: str,
    account_id: int = 1,
    auto_unique: bool = True,
) -> dict:
    """Create a test student on Canvas and persist locally.

    If *auto_unique* is True (default), and the email is already taken on
    Canvas, the function will retry once with a UUID-suffixed email so the
    caller never has to worry about collisions.
    """
    actual_email = email
    result = await canvas_service.create_canvas_user(
        token, base_url, account_id, name, actual_email
    )

    # Retry with unique-ified email on "unique_id taken" error
    if not result["success"] and auto_unique and "đã tồn tại" in result.get("error", ""):
        local_part, _, domain = email.partition("@")
        suffix = uuid.uuid4().hex[:6]
        actual_email = f"{local_part}+sim{suffix}@{domain}" if domain else f"{email}_{suffix}"
        logger.info(f"Email {email} taken — retrying with {actual_email}")
        result = await canvas_service.create_canvas_user(
            token, base_url, account_id, name, actual_email
        )

    await _audit(
        db,
        user_id=owner_id,
        action=AuditAction.CREATE_USER,
        canvas_domain=base_url,
        success=result["success"],
        canvas_user_id=result.get("canvas_user_id"),
        detail=json.dumps({"name": name, "email": actual_email, "account_id": account_id}),
    )

    if not result["success"]:
        return result

    student = TestStudent(
        owner_id=owner_id,
        canvas_user_id=result["canvas_user_id"],
        canvas_domain=base_url,
        display_name=name,
        email=actual_email,
        status=TestStudentStatus.ACTIVE,
    )
    db.add(student)
    await db.flush()

    return {
        "success": True,
        "test_student": {
            "id": str(student.id),
            "canvas_user_id": student.canvas_user_id,
            "display_name": student.display_name,
            "email": student.email,
            "status": student.status.value,
            "canvas_domain": student.canvas_domain,
        },
    }


async def list_test_students(
    db: AsyncSession,
    owner_id: uuid.UUID,
    canvas_domain: str | None = None,
) -> list[dict]:
    """Return all test students belonging to the owner."""
    stmt = (
        select(TestStudent)
        .where(TestStudent.owner_id == owner_id)
        .order_by(TestStudent.created_at.desc())
    )
    if canvas_domain:
        stmt = stmt.where(TestStudent.canvas_domain == canvas_domain)

    result = await db.execute(stmt)
    students = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "canvas_user_id": s.canvas_user_id,
            "display_name": s.display_name,
            "email": s.email,
            "status": s.status.value,
            "canvas_domain": s.canvas_domain,
            "current_course_id": s.current_course_id,
            "current_enrollment_id": s.current_enrollment_id,
            "created_at": s.created_at.isoformat(),
        }
        for s in students
    ]


async def delete_test_student(
    db: AsyncSession,
    token: str,
    base_url: str,
    *,
    owner_id: uuid.UUID,
    test_student_id: str,
    account_id: int = 1,
    hard_delete_on_canvas: bool = True,
) -> dict:
    """
    Delete a test student:
      1. Unenroll from current course (if enrolled)
      2. Delete user on Canvas (if hard_delete_on_canvas)
      3. Mark as DELETED locally
    """
    stmt = select(TestStudent).where(
        TestStudent.id == uuid.UUID(test_student_id),
        TestStudent.owner_id == owner_id,
    )
    result = await db.execute(stmt)
    student = result.scalar_one_or_none()
    if not student:
        return {"success": False, "error": "Test student not found"}

    canvas_uid = student.canvas_user_id
    cleanup_errors: list[str] = []

    # 1. Unenroll from current course if enrolled
    if student.current_enrollment_id and student.current_course_id:
        unenroll_res = await canvas_service.unenroll_user(
            token, base_url,
            student.current_course_id,
            student.current_enrollment_id,
            task="delete",
        )
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.UNENROLL_USER,
            canvas_domain=base_url,
            success=unenroll_res["success"],
            canvas_course_id=student.current_course_id,
            canvas_user_id=canvas_uid,
            detail=json.dumps(unenroll_res.get("error") or "unenrolled"),
        )
        if not unenroll_res["success"]:
            cleanup_errors.append(f"Unenroll failed: {unenroll_res['error']}")

    # 2. Delete user on Canvas
    if hard_delete_on_canvas and canvas_uid:
        del_res = await canvas_service.delete_canvas_user(
            token, base_url, account_id, canvas_uid
        )
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.DELETE_USER,
            canvas_domain=base_url,
            success=del_res["success"],
            canvas_user_id=canvas_uid,
            detail=json.dumps(del_res.get("error") or "deleted from Canvas"),
        )
        if not del_res["success"]:
            cleanup_errors.append(f"Canvas delete failed: {del_res['error']}")

    # 3. Mark as DELETED locally
    student.status = TestStudentStatus.DELETED
    student.current_enrollment_id = None
    student.current_course_id = None
    await db.flush()

    msg = f"Test student {student.display_name} deleted"
    if cleanup_errors:
        msg += f" (warnings: {'; '.join(cleanup_errors)})"

    return {"success": True, "message": msg, "warnings": cleanup_errors}


# ============================================================================
# Simulation Execution
# ============================================================================

async def execute_simulation(
    db: AsyncSession,
    token: str,
    base_url: str,
    *,
    owner_id: uuid.UUID,
    course_id: int,
    quiz_id: int,
    test_student_id: str,
    answers: list[dict],
    access_code: str | None = None,
) -> dict:
    """
    Full simulation lifecycle:
      1. Validate test student
      2. Enroll student in course (if not already)
      3. Start quiz submission (masquerade)
      4. Answer questions (masquerade)
      5. Complete submission (masquerade)
      6. Record result & audit
    """

    # ── 0. Create SimulationRun ──────────────────────────────────────────
    run = SimulationRun(
        owner_id=owner_id,
        course_id=course_id,
        quiz_id=quiz_id,
        test_student_id=uuid.UUID(test_student_id),
        status=SimulationStatus.PENDING,
        answers_payload=answers,
    )
    db.add(run)
    await db.flush()  # get run.id

    # ── 1. Fetch test student ────────────────────────────────────────────
    stmt = select(TestStudent).where(
        TestStudent.id == uuid.UUID(test_student_id),
        TestStudent.owner_id == owner_id,
    )
    result = await db.execute(stmt)
    student = result.scalar_one_or_none()
    if not student:
        run.status = SimulationStatus.FAILED
        run.error_message = "Test student not found"
        return {"success": False, "error": run.error_message, "run_id": str(run.id)}

    canvas_uid = student.canvas_user_id

    # ── 2. Enroll (if needed) ────────────────────────────────────────────
    run.status = SimulationStatus.ENROLLING
    await db.flush()

    need_enroll = (
        student.current_course_id != course_id
        or student.status != TestStudentStatus.ENROLLED
    )

    if need_enroll:
        enroll_res = await canvas_service.enroll_user(
            token, base_url, course_id, canvas_uid
        )
        await _audit(
            db,
            user_id=owner_id,
            action=AuditAction.ENROLL_USER,
            canvas_domain=base_url,
            success=enroll_res["success"],
            simulation_run_id=run.id,
            canvas_course_id=course_id,
            canvas_user_id=canvas_uid,
            detail=json.dumps(enroll_res.get("error") or "enrolled"),
        )
        if not enroll_res["success"]:
            run.status = SimulationStatus.FAILED
            run.error_message = f"Enrollment failed: {enroll_res['error']}"
            return {"success": False, "error": run.error_message, "run_id": str(run.id)}

        student.current_course_id = course_id
        student.current_enrollment_id = enroll_res.get("enrollment_id")
        student.status = TestStudentStatus.ENROLLED
        await db.flush()

    # ── 3. Start quiz submission (masquerade) ────────────────────────────
    run.status = SimulationStatus.SUBMITTING
    await db.flush()

    start_res = await canvas_service.start_quiz_submission(
        token, base_url, course_id, quiz_id,
        as_user_id=canvas_uid,
        access_code=access_code,
    )
    await _audit(
        db,
        user_id=owner_id,
        action=AuditAction.START_SUBMISSION,
        canvas_domain=base_url,
        success=start_res["success"],
        simulation_run_id=run.id,
        canvas_course_id=course_id,
        canvas_user_id=canvas_uid,
        canvas_quiz_id=quiz_id,
        detail=json.dumps(start_res.get("error") or "ok"),
    )

    if not start_res["success"]:
        run.status = SimulationStatus.FAILED
        run.error_message = f"Start submission failed: {start_res['error']}"
        return {"success": False, "error": run.error_message, "run_id": str(run.id)}

    qs_id = start_res["quiz_submission_id"]
    attempt = start_res["attempt"]
    validation_token = start_res["validation_token"]

    run.canvas_submission_id = qs_id
    run.attempt_number = attempt

    # ── 4. Answer questions (masquerade) ─────────────────────────────────
    formatted_answers = [
        {"id": a["question_id"], "answer": a["answer"]} for a in answers
    ]

    answer_res = await canvas_service.answer_quiz_questions(
        token, base_url,
        quiz_submission_id=qs_id,
        attempt=attempt,
        validation_token=validation_token,
        answers=formatted_answers,
        as_user_id=canvas_uid,
        access_code=access_code,
    )
    await _audit(
        db,
        user_id=owner_id,
        action=AuditAction.ANSWER_QUESTIONS,
        canvas_domain=base_url,
        success=answer_res["success"],
        simulation_run_id=run.id,
        canvas_course_id=course_id,
        canvas_user_id=canvas_uid,
        canvas_quiz_id=quiz_id,
        canvas_submission_id=qs_id,
        detail=json.dumps(answer_res.get("error") or f"{len(formatted_answers)} answers"),
    )

    if not answer_res["success"]:
        run.status = SimulationStatus.FAILED
        run.error_message = f"Answer failed: {answer_res['error']}"
        return {"success": False, "error": run.error_message, "run_id": str(run.id)}

    # ── 5. Complete submission (masquerade) ──────────────────────────────
    complete_res = await canvas_service.complete_quiz_submission(
        token, base_url,
        course_id=course_id,
        quiz_id=quiz_id,
        submission_id=qs_id,
        attempt=attempt,
        validation_token=validation_token,
        as_user_id=canvas_uid,
        access_code=access_code,
    )
    await _audit(
        db,
        user_id=owner_id,
        action=AuditAction.COMPLETE_SUBMISSION,
        canvas_domain=base_url,
        success=complete_res["success"],
        simulation_run_id=run.id,
        canvas_course_id=course_id,
        canvas_user_id=canvas_uid,
        canvas_quiz_id=quiz_id,
        canvas_submission_id=qs_id,
        detail=json.dumps(complete_res.get("error") or f"score={complete_res.get('score')}"),
    )

    if not complete_res["success"]:
        run.status = SimulationStatus.PARTIAL
        run.error_message = f"Complete failed: {complete_res['error']}"
        return {"success": False, "error": run.error_message, "run_id": str(run.id)}

    # ── 6. Record result ─────────────────────────────────────────────────
    run.score = complete_res.get("score")
    run.kept_score = complete_res.get("kept_score")
    qs = complete_res.get("quiz_submission", {})
    run.points_possible = qs.get("quiz_points_possible")
    run.status = SimulationStatus.COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    await db.flush()

    return {
        "success": True,
        "run_id": str(run.id),
        "canvas_submission_id": qs_id,
        "attempt": attempt,
        "score": run.score,
        "kept_score": run.kept_score,
        "points_possible": run.points_possible,
        "status": run.status.value,
    }


async def execute_batch_simulation(
    db: AsyncSession,
    token: str,
    base_url: str,
    *,
    owner_id: uuid.UUID,
    course_id: int,
    quiz_id: int,
    test_student_id: str,
    answer_sets: list[list[dict]],
    access_code: str | None = None,
) -> dict:
    """Run multiple simulation attempts sequentially."""
    results: list[dict] = []
    for idx, answers in enumerate(answer_sets):
        logger.info(f"Batch simulation attempt {idx + 1}/{len(answer_sets)}")
        res = await execute_simulation(
            db, token, base_url,
            owner_id=owner_id,
            course_id=course_id,
            quiz_id=quiz_id,
            test_student_id=test_student_id,
            answers=answers,
            access_code=access_code,
        )
        results.append(res)
        if not res["success"]:
            logger.warning(f"Batch attempt {idx + 1} failed: {res.get('error')}")

    total = len(results)
    succeeded = sum(1 for r in results if r.get("success"))
    return {
        "success": succeeded > 0,
        "total": total,
        "succeeded": succeeded,
        "failed": total - succeeded,
        "results": results,
    }


# ============================================================================
# History
# ============================================================================

async def list_simulation_runs(
    db: AsyncSession,
    owner_id: uuid.UUID,
    *,
    course_id: int | None = None,
    quiz_id: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return simulation run history for the owner."""
    stmt = (
        select(SimulationRun)
        .where(SimulationRun.owner_id == owner_id)
        .order_by(SimulationRun.started_at.desc())
        .limit(limit)
    )
    if course_id is not None:
        stmt = stmt.where(SimulationRun.course_id == course_id)
    if quiz_id is not None:
        stmt = stmt.where(SimulationRun.quiz_id == quiz_id)

    result = await db.execute(stmt)
    runs = result.scalars().all()

    output = []
    for r in runs:
        output.append({
            "id": str(r.id),
            "course_id": r.course_id,
            "quiz_id": r.quiz_id,
            "canvas_submission_id": r.canvas_submission_id,
            "attempt_number": r.attempt_number,
            "score": r.score,
            "kept_score": r.kept_score,
            "points_possible": r.points_possible,
            "status": r.status.value,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })
    return output


async def list_audit_logs(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 100,
) -> list[dict]:
    """Return audit entries for the user."""
    stmt = (
        select(CanvasAuditLog)
        .where(CanvasAuditLog.user_id == user_id)
        .order_by(CanvasAuditLog.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "action": log.action.value,
            "canvas_domain": log.canvas_domain,
            "canvas_course_id": log.canvas_course_id,
            "canvas_user_id": log.canvas_user_id,
            "canvas_quiz_id": log.canvas_quiz_id,
            "canvas_submission_id": log.canvas_submission_id,
            "success": log.success,
            "detail": log.detail,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
