"""
Job Service
============
Service layer for background job management.
Provides CRUD operations, idempotency, progress tracking, and job control.
"""
import uuid
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Union

from sqlalchemy import select, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database.models import Job, JobEvent, JobType, JobStatus, JobEventLevel
from backend.celery_app import revoke_task

logger = logging.getLogger(__name__)


class JobService:
    """
    Service for managing background jobs.
    
    Provides:
    - Create jobs with idempotency support
    - Update job status and progress
    - Query jobs by user, type, status
    - Cancel/revoke running jobs
    - Add job events for observability
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize with database session.
        
        Args:
            db: Async SQLAlchemy session
        """
        self.db = db
    
    # =========================================================================
    # Job Creation
    # =========================================================================
    
    async def create_job(
        self,
        job_type: JobType,
        user_id: Optional[uuid.UUID] = None,
        payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 5,
    ) -> Job:
        """
        Create a new job record.
        
        Args:
            job_type: Type of job
            user_id: Optional owner user ID
            payload: Request parameters (sanitized)
            idempotency_key: Unique key for idempotent creation
            max_retries: Maximum retry attempts
            
        Returns:
            Created Job instance
            
        Raises:
            ValueError: If idempotency_key exists with non-terminal job
        """
        # Check idempotency
        if idempotency_key:
            existing = await self.get_by_idempotency_key(idempotency_key)
            if existing:
                if not existing.is_terminal:
                    logger.info(f"Returning existing job for idempotency_key={idempotency_key}")
                    return existing
                # If existing job is terminal, we can create a new one
                # by removing the idempotency key from the old job
                existing.idempotency_key = None
                await self.db.flush()
        
        job = Job(
            job_type=job_type,
            user_id=user_id,
            status=JobStatus.QUEUED,
            payload_json=payload,
            idempotency_key=idempotency_key,
            max_retries=max_retries,
        )
        
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        
        logger.info(f"Created job {job.id} type={job_type.value} user={user_id}")
        
        # Add creation event
        await self.add_event(
            job_id=job.id,
            level=JobEventLevel.INFO,
            message=f"Job created: {job_type.value}",
        )
        
        return job
    
    async def get_or_create_job(
        self,
        job_type: JobType,
        idempotency_key: str,
        user_id: Optional[uuid.UUID] = None,
        payload: Optional[Dict[str, Any]] = None,
        max_retries: int = 5,
    ) -> tuple[Job, bool]:
        """
        Get existing job by idempotency key or create new one.
        
        Args:
            job_type: Type of job
            idempotency_key: Unique key for idempotent creation
            user_id: Optional owner user ID
            payload: Request parameters
            max_retries: Maximum retry attempts
            
        Returns:
            Tuple of (Job, created: bool)
        """
        existing = await self.get_by_idempotency_key(idempotency_key)
        if existing and not existing.is_terminal:
            return existing, False
        
        job = await self.create_job(
            job_type=job_type,
            user_id=user_id,
            payload=payload,
            idempotency_key=idempotency_key,
            max_retries=max_retries,
        )
        return job, True
    
    # =========================================================================
    # Job Retrieval
    # =========================================================================
    
    async def get_by_id(self, job_id: uuid.UUID) -> Optional[Job]:
        """Get job by ID."""
        result = await self.db.execute(
            select(Job).where(Job.id == job_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_idempotency_key(self, key: str) -> Optional[Job]:
        """Get job by idempotency key."""
        result = await self.db.execute(
            select(Job).where(Job.idempotency_key == key)
        )
        return result.scalar_one_or_none()
    
    async def get_by_celery_task_id(self, task_id: str) -> Optional[Job]:
        """Get job by Celery task ID."""
        result = await self.db.execute(
            select(Job).where(Job.celery_task_id == task_id)
        )
        return result.scalar_one_or_none()
    
    async def list_jobs(
        self,
        user_id: Optional[uuid.UUID] = None,
        job_type: Optional[JobType] = None,
        status: Optional[Union[JobStatus, List[JobStatus]]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Job]:
        """
        List jobs with optional filters.
        
        Args:
            user_id: Filter by user
            job_type: Filter by job type
            status: Filter by status (single or list)
            limit: Maximum results
            offset: Pagination offset
            
        Returns:
            List of Job instances
        """
        query = select(Job).order_by(Job.created_at.desc())
        
        conditions = []
        if user_id:
            conditions.append(Job.user_id == user_id)
        if job_type:
            conditions.append(Job.job_type == job_type)
        if status:
            if isinstance(status, list):
                conditions.append(Job.status.in_(status))
            else:
                conditions.append(Job.status == status)
        
        if conditions:
            query = query.where(and_(*conditions))
        
        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def count_jobs(
        self,
        user_id: Optional[uuid.UUID] = None,
        status: Optional[Union[JobStatus, List[JobStatus]]] = None,
    ) -> int:
        """Count jobs with optional filters."""
        from sqlalchemy import func
        
        query = select(func.count(Job.id))
        
        conditions = []
        if user_id:
            conditions.append(Job.user_id == user_id)
        if status:
            if isinstance(status, list):
                conditions.append(Job.status.in_(status))
            else:
                conditions.append(Job.status == status)
        
        if conditions:
            query = query.where(and_(*conditions))
        
        result = await self.db.execute(query)
        return result.scalar() or 0
    
    # =========================================================================
    # Job Status Updates
    # =========================================================================
    
    async def set_celery_task_id(
        self,
        job_id: uuid.UUID,
        task_id: str,
    ) -> Job:
        """Associate Celery task ID with job."""
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.celery_task_id = task_id
        await self.db.flush()
        
        logger.info(f"Job {job_id} linked to Celery task {task_id}")
        return job
    
    async def start_job(
        self,
        job_id: uuid.UUID,
        current_step: Optional[str] = None,
    ) -> Job:
        """Mark job as started."""
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.status = JobStatus.STARTED
        job.started_at = datetime.now(timezone.utc)
        if current_step:
            job.current_step = current_step
        
        await self.db.flush()
        
        await self.add_event(
            job_id=job_id,
            level=JobEventLevel.INFO,
            message=f"Job started: {current_step or 'Processing'}",
        )
        
        logger.info(f"Job {job_id} started")
        return job
    
    async def update_progress(
        self,
        job_id: uuid.UUID,
        progress_pct: int,
        current_step: Optional[str] = None,
        add_event: bool = False,
    ) -> Job:
        """
        Update job progress.
        
        Args:
            job_id: Job ID
            progress_pct: Progress percentage (0-100)
            current_step: Current step description
            add_event: Whether to add a progress event
        """
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.status = JobStatus.PROGRESS
        job.progress_pct = min(100, max(0, progress_pct))
        if current_step:
            job.current_step = current_step
        
        await self.db.flush()
        
        if add_event:
            await self.add_event(
                job_id=job_id,
                level=JobEventLevel.INFO,
                message=f"Progress: {progress_pct}% - {current_step or 'Processing'}",
            )
        
        return job
    
    async def complete_job(
        self,
        job_id: uuid.UUID,
        result: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Mark job as successfully completed."""
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.status = JobStatus.SUCCEEDED
        job.progress_pct = 100
        job.result_json = result
        job.completed_at = datetime.now(timezone.utc)
        
        await self.db.flush()
        
        await self.add_event(
            job_id=job_id,
            level=JobEventLevel.INFO,
            message="Job completed successfully",
        )
        
        duration = job.duration_seconds
        logger.info(f"Job {job_id} completed in {duration:.2f}s" if duration else f"Job {job_id} completed")
        return job
    
    async def fail_job(
        self,
        job_id: uuid.UUID,
        error_message: str,
        error_stack: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Mark job as failed."""
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.status = JobStatus.FAILED
        job.error_message = error_message
        job.error_stack = error_stack or traceback.format_exc()
        job.completed_at = datetime.now(timezone.utc)
        if result:
            job.result_json = result
        
        await self.db.flush()
        
        await self.add_event(
            job_id=job_id,
            level=JobEventLevel.ERROR,
            message=f"Job failed: {error_message}",
        )
        
        logger.error(f"Job {job_id} failed: {error_message}")
        return job
    
    async def increment_retry(
        self,
        job_id: uuid.UUID,
        error_message: str,
    ) -> tuple[Job, bool]:
        """
        Increment retry count and check if more retries available.
        
        Returns:
            Tuple of (Job, can_retry: bool)
        """
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        job.retry_count += 1
        can_retry = job.retry_count < job.max_retries
        
        if not can_retry:
            job.status = JobStatus.FAILED
            job.error_message = error_message
            job.completed_at = datetime.now(timezone.utc)
        else:
            job.status = JobStatus.QUEUED
        
        await self.db.flush()
        
        await self.add_event(
            job_id=job_id,
            level=JobEventLevel.WARNING,
            message=f"Retry {job.retry_count}/{job.max_retries}: {error_message}",
        )
        
        return job, can_retry
    
    async def cancel_job(
        self,
        job_id: uuid.UUID,
        terminate_worker: bool = False,
    ) -> Job:
        """
        Cancel a job.
        
        Args:
            job_id: Job to cancel
            terminate_worker: If True, terminate running task (SIGTERM)
            
        Returns:
            Updated Job
        """
        job = await self.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        
        if job.is_terminal:
            raise ValueError(f"Cannot cancel terminal job: {job.status.value}")
        
        # Revoke Celery task if exists
        if job.celery_task_id:
            revoke_task(job.celery_task_id, terminate=terminate_worker)
        
        job.status = JobStatus.CANCELED
        job.completed_at = datetime.now(timezone.utc)
        
        await self.db.flush()
        
        await self.add_event(
            job_id=job_id,
            level=JobEventLevel.WARNING,
            message="Job canceled by user",
        )
        
        logger.info(f"Job {job_id} canceled")
        return job
    
    # =========================================================================
    # Job Events
    # =========================================================================
    
    async def add_event(
        self,
        job_id: uuid.UUID,
        level: JobEventLevel,
        message: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> JobEvent:
        """Add an event to a job."""
        event = JobEvent(
            job_id=job_id,
            level=level,
            message=message,
            meta_json=meta,
        )
        self.db.add(event)
        await self.db.flush()
        return event
    
    async def get_events(
        self,
        job_id: uuid.UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[JobEvent]:
        """Get events for a job."""
        result = await self.db.execute(
            select(JobEvent)
            .where(JobEvent.job_id == job_id)
            .order_by(JobEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
    
    async def get_job_with_events(
        self,
        job_id: uuid.UUID,
        event_limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """Get job with recent events."""
        job = await self.get_by_id(job_id)
        if not job:
            return None
        
        events = await self.get_events(job_id, limit=event_limit)
        
        result = job.to_dict()
        result["events"] = [e.to_dict() for e in events]
        return result


# =============================================================================
# Sync wrapper for Celery tasks
# =============================================================================

class SyncJobService:
    """
    Synchronous job service for use in Celery tasks.
    Uses synchronous database sessions.
    """
    
    def __init__(self, db_session):
        """Initialize with sync SQLAlchemy session."""
        from sqlalchemy.orm import Session
        self.db: Session = db_session
    
    def get_by_id(self, job_id: uuid.UUID) -> Optional[Job]:
        """Get job by ID."""
        return self.db.query(Job).filter(Job.id == job_id).first()
    
    def update_progress(
        self,
        job_id: uuid.UUID,
        progress_pct: int,
        current_step: Optional[str] = None,
    ) -> Optional[Job]:
        """Update job progress."""
        job = self.get_by_id(job_id)
        if not job:
            return None
        
        job.status = JobStatus.PROGRESS
        job.progress_pct = min(100, max(0, progress_pct))
        if current_step:
            job.current_step = current_step
        job.updated_at = datetime.now(timezone.utc)
        
        self.db.commit()
        return job
    
    def start_job(self, job_id: uuid.UUID, current_step: Optional[str] = None) -> Optional[Job]:
        """Mark job as started."""
        job = self.get_by_id(job_id)
        if not job:
            return None
        
        job.status = JobStatus.STARTED
        job.started_at = datetime.now(timezone.utc)
        if current_step:
            job.current_step = current_step
        
        self.db.commit()
        self._add_event(job_id, JobEventLevel.INFO, f"Started: {current_step or 'Processing'}")
        return job
    
    def complete_job(
        self,
        job_id: uuid.UUID,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Job]:
        """Mark job as completed."""
        job = self.get_by_id(job_id)
        if not job:
            return None
        
        job.status = JobStatus.SUCCEEDED
        job.progress_pct = 100
        job.result_json = result
        job.completed_at = datetime.now(timezone.utc)
        
        self.db.commit()
        self._add_event(job_id, JobEventLevel.INFO, "Completed successfully")
        return job
    
    def fail_job(
        self,
        job_id: uuid.UUID,
        error_message: str,
        error_stack: Optional[str] = None,
    ) -> Optional[Job]:
        """Mark job as failed."""
        job = self.get_by_id(job_id)
        if not job:
            return None
        
        job.status = JobStatus.FAILED
        job.error_message = error_message
        job.error_stack = error_stack
        job.completed_at = datetime.now(timezone.utc)
        
        self.db.commit()
        self._add_event(job_id, JobEventLevel.ERROR, f"Failed: {error_message}")
        return job
    
    def _add_event(
        self,
        job_id: uuid.UUID,
        level: JobEventLevel,
        message: str,
        meta: Optional[Dict[str, Any]] = None,
    ):
        """Add event to job."""
        event = JobEvent(
            job_id=job_id,
            level=level,
            message=message,
            meta_json=meta,
        )
        self.db.add(event)
        self.db.commit()


def get_sync_job_service():
    """Get sync job service with fresh session."""
    from backend.database.base import SessionLocal
    session = SessionLocal()
    return SyncJobService(session), session
