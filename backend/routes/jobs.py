"""
Jobs API Routes
===============
REST endpoints for job status, cancellation, and real-time events.
"""
import logging
import asyncio
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_async_session
from backend.auth.dependencies import CurrentUser
from backend.services.job_service import JobService
from backend.database.models.job import JobStatus, JobType, JobEventLevel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# --- Pydantic Schemas ---

class JobEventOut(BaseModel):
    """Job event output schema."""
    id: str
    level: str
    message: str
    meta: Optional[dict] = None
    created_at: str

    class Config:
        from_attributes = True


class JobOut(BaseModel):
    """Job output schema."""
    id: str
    job_type: str
    status: str
    progress_pct: int
    current_step: Optional[str] = None
    celery_task_id: Optional[str] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    class Config:
        from_attributes = True


class JobListOut(BaseModel):
    """Paginated job list."""
    items: List[JobOut]
    total: int
    page: int
    page_size: int
    pages: int


class CancelResponse(BaseModel):
    """Cancel response."""
    success: bool
    message: str


class RetryResponse(BaseModel):
    """Retry response."""
    success: bool
    new_job_id: Optional[str] = None
    message: str


# --- Route Helpers ---

def _job_to_out(job) -> JobOut:
    """Convert Job model to output schema."""
    return JobOut(
        id=str(job.id),
        job_type=job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type),
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        progress_pct=job.progress_pct,
        current_step=job.current_step,
        celery_task_id=job.celery_task_id,
        result=job.result_json,
        error_message=job.error_message,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _event_to_out(event) -> JobEventOut:
    """Convert JobEvent model to output schema."""
    return JobEventOut(
        id=str(event.id),
        level=event.level.value if hasattr(event.level, "value") else str(event.level),
        message=event.message,
        meta=event.meta_json,
        created_at=event.created_at.isoformat() if event.created_at else None,
    )


# --- Routes ---

@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get job status by ID.
    
    Returns current status, progress, and result (if completed).
    """
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return _job_to_out(job)


@router.get("", response_model=JobListOut)
async def list_jobs(
    user: CurrentUser,
    user_id: Optional[UUID] = Query(None, description="Filter by user ID"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    List jobs with optional filters and pagination.
    """
    from sqlalchemy import select, func
    from backend.database.models.job import Job
    
    job_service = JobService(db)
    
    # Build query
    query = select(Job).order_by(Job.created_at.desc())
    count_query = select(func.count(Job.id))
    
    if user_id:
        query = query.where(Job.user_id == user_id)
        count_query = count_query.where(Job.user_id == user_id)
    
    if job_type:
        try:
            jt = JobType(job_type)
            query = query.where(Job.job_type == jt)
            count_query = count_query.where(Job.job_type == jt)
        except ValueError:
            pass
    
    if status:
        try:
            st = JobStatus(status)
            query = query.where(Job.status == st)
            count_query = count_query.where(Job.status == st)
        except ValueError:
            pass
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    return JobListOut(
        items=[_job_to_out(j) for j in jobs],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.post("/{job_id}/cancel", response_model=CancelResponse)
async def cancel_job(
    job_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Cancel a queued or running job.
    
    Revokes the Celery task if it hasn't started yet.
    """
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED]:
        return CancelResponse(
            success=False,
            message=f"Job already in terminal state: {job.status.value}",
        )
    
    # Revoke Celery task
    if job.celery_task_id:
        from backend.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    
    # Update job status
    await job_service.cancel_job(job_id)
    
    return CancelResponse(success=True, message="Job canceled")


@router.get("/{job_id}/events", response_model=List[JobEventOut])
async def get_job_events(
    job_id: UUID,
    user: CurrentUser,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get all events for a job.
    """
    from sqlalchemy import select
    from backend.database.models.job import JobEvent
    
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    query = (
        select(JobEvent)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.created_at.asc())
        .limit(limit)
    )
    
    result = await db.execute(query)
    events = result.scalars().all()
    
    return [_event_to_out(e) for e in events]


@router.get("/{job_id}/stream")
async def stream_job_events(
    job_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    SSE endpoint for real-time job updates.
    
    Streams:
    - progress updates
    - status changes
    - completion/failure events
    
    Connection closes when job reaches terminal state.
    """
    import json
    
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    async def event_generator():
        """Generate SSE events."""
        last_progress = -1
        last_status = None
        poll_interval = 0.5  # seconds
        max_polls = 7200  # 1 hour max
        
        for _ in range(max_polls):
            # Refresh job from DB
            job = await job_service.get_by_id(job_id)
            if not job:
                yield f"event: error\ndata: {json.dumps({'error': 'Job not found'})}\n\n"
                break
            
            # Send update if changed
            if job.progress_pct != last_progress or job.status != last_status:
                data = {
                    "id": str(job.id),
                    "status": job.status.value,
                    "progress_pct": job.progress_pct,
                    "current_step": job.current_step,
                }
                
                if job.status == JobStatus.SUCCEEDED:
                    data["result"] = job.result_json
                    yield f"event: complete\ndata: {json.dumps(data)}\n\n"
                    break
                elif job.status == JobStatus.FAILED:
                    data["error"] = job.error_message
                    yield f"event: failed\ndata: {json.dumps(data)}\n\n"
                    break
                elif job.status == JobStatus.CANCELED:
                    yield f"event: canceled\ndata: {json.dumps(data)}\n\n"
                    break
                else:
                    yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                
                last_progress = job.progress_pct
                last_status = job.status
            
            await asyncio.sleep(poll_interval)
        
        yield f"event: close\ndata: {json.dumps({'message': 'Stream ended'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/retry", response_model=RetryResponse)
async def retry_job(
    job_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Retry a failed job.
    
    Creates a new job with the same parameters and queues it.
    """
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != JobStatus.FAILED:
        return RetryResponse(
            success=False,
            message=f"Can only retry failed jobs. Current status: {job.status.value}",
        )
    
    # Create new job with same parameters
    new_job = await job_service.create_job(
        user_id=job.user_id,
        job_type=job.job_type,
        payload=job.payload_json,
        idempotency_key=None,  # Generate new key
    )
    
    # Queue the appropriate task based on job type
    # This mapping should match your task definitions
    from backend import tasks
    
    task_map = {
        JobType.INGEST_DOCUMENT: tasks.rag_tasks.ingest_document,
        JobType.BUILD_INDEX: tasks.rag_tasks.build_index,
        JobType.RAG_QUERY: tasks.rag_tasks.query_documents,
        JobType.EXTRACT_TOPICS: tasks.rag_tasks.extract_topics,
        JobType.GENERATE_QUIZ: tasks.llm_tasks.generate_quiz,
        JobType.CANVAS_FILE_DOWNLOAD: tasks.canvas_tasks.download_file,
        JobType.CANVAS_QTI_IMPORT: tasks.canvas_tasks.import_qti,
        JobType.CANVAS_INDEX_FILE: tasks.rag_tasks.canvas_index_file,
    }
    
    task_func = task_map.get(job.job_type)
    if not task_func:
        return RetryResponse(
            success=False,
            message=f"No retry handler for job type: {job.job_type.value}",
        )
    
    # Apply task
    from backend.celery_app import apply_async_nonblocking
    result = await apply_async_nonblocking(
        task_func,
        args=[str(new_job.id)],
        kwargs=job.payload_json or {},
    )
    
    # Update with Celery task ID
    await job_service.set_celery_task_id(new_job.id, result.id)
    
    return RetryResponse(
        success=True,
        new_job_id=str(new_job.id),
        message="Job queued for retry",
    )


@router.delete("/{job_id}")
async def delete_job(
    job_id: UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Delete a job and its events.
    
    Only jobs in terminal states can be deleted.
    """
    from sqlalchemy import delete
    from backend.database.models.job import Job, JobEvent
    
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status not in [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELED]:
        raise HTTPException(
            status_code=400,
            detail="Can only delete jobs in terminal states",
        )
    
    # Delete events first
    await db.execute(delete(JobEvent).where(JobEvent.job_id == job_id))
    # Delete job
    await db.execute(delete(Job).where(Job.id == job_id))
    await db.commit()
    
    return {"success": True, "message": "Job deleted"}
