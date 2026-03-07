"""
Admin Service
Provides administrative operations: user management, dashboard stats, system overview.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, update, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    User, UserRole, UserStatus,
    Job, JobStatus, JobType,
    CanvasToken,
)
from backend.core.security import hash_password
from backend.core.exceptions import (
    BadRequestException,
    NotFoundException,
)

logger = logging.getLogger(__name__)


class AdminService:
    """Administrative operations for user and system management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Dashboard Statistics
    # =========================================================================

    async def get_dashboard_stats(self) -> dict:
        """Get system-wide statistics for the admin dashboard."""
        now = datetime.now(timezone.utc)
        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)

        # --- User stats ---
        user_total = await self.db.scalar(select(func.count(User.id))) or 0
        user_active = await self.db.scalar(
            select(func.count(User.id)).where(User.status == UserStatus.ACTIVE)
        ) or 0
        user_disabled = await self.db.scalar(
            select(func.count(User.id)).where(User.status == UserStatus.DISABLED)
        ) or 0
        user_pending = await self.db.scalar(
            select(func.count(User.id)).where(User.status == UserStatus.PENDING)
        ) or 0
        new_users_24h = await self.db.scalar(
            select(func.count(User.id)).where(User.created_at >= last_24h)
        ) or 0
        new_users_7d = await self.db.scalar(
            select(func.count(User.id)).where(User.created_at >= last_7d)
        ) or 0

        # --- Job stats ---
        job_total = await self.db.scalar(select(func.count(Job.id))) or 0
        job_succeeded = await self.db.scalar(
            select(func.count(Job.id)).where(Job.status == JobStatus.SUCCEEDED)
        ) or 0
        job_failed = await self.db.scalar(
            select(func.count(Job.id)).where(Job.status == JobStatus.FAILED)
        ) or 0
        job_running = await self.db.scalar(
            select(func.count(Job.id)).where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.STARTED, JobStatus.PROGRESS])
            )
        ) or 0
        jobs_24h = await self.db.scalar(
            select(func.count(Job.id)).where(Job.created_at >= last_24h)
        ) or 0

        # --- Job type distribution ---
        type_dist_rows = (
            await self.db.execute(
                select(Job.job_type, func.count(Job.id))
                .group_by(Job.job_type)
                .order_by(func.count(Job.id).desc())
            )
        ).all()
        job_type_distribution = {
            (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
            for row in type_dist_rows
        }

        # --- Canvas token stats ---
        canvas_tokens_total = await self.db.scalar(
            select(func.count(CanvasToken.id))
        ) or 0
        canvas_tokens_active = await self.db.scalar(
            select(func.count(CanvasToken.id)).where(CanvasToken.revoked_at.is_(None))
        ) or 0

        # --- Success rate ---
        completed = job_succeeded + job_failed
        success_rate = round((job_succeeded / completed * 100), 1) if completed > 0 else 0.0

        return {
            "users": {
                "total": user_total,
                "active": user_active,
                "disabled": user_disabled,
                "pending": user_pending,
                "new_24h": new_users_24h,
                "new_7d": new_users_7d,
            },
            "jobs": {
                "total": job_total,
                "succeeded": job_succeeded,
                "failed": job_failed,
                "running": job_running,
                "last_24h": jobs_24h,
                "success_rate": success_rate,
                "type_distribution": job_type_distribution,
            },
            "canvas_tokens": {
                "total": canvas_tokens_total,
                "active": canvas_tokens_active,
            },
        }

    # =========================================================================
    # User Management
    # =========================================================================

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        """
        List users with filtering and pagination.
        
        Returns:
            Tuple of (users, total_count)
        """
        query = select(User).order_by(User.created_at.desc())
        count_query = select(func.count(User.id))

        if role:
            query = query.where(User.role == role)
            count_query = count_query.where(User.role == role)

        if status:
            query = query.where(User.status == status)
            count_query = count_query.where(User.status == status)

        if search:
            like_pattern = f"%{search}%"
            search_filter = (User.email.ilike(like_pattern)) | (User.name.ilike(like_pattern))
            query = query.where(search_filter)
            count_query = count_query.where(search_filter)

        total = await self.db.scalar(count_query) or 0

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        users = list(result.scalars().all())

        return users, total

    async def get_user(self, user_id: UUID) -> User:
        """Get a single user by ID."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundException(detail="User not found")
        return user

    async def update_user(
        self,
        user_id: UUID,
        *,
        name: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
    ) -> User:
        """Update user fields (admin-only)."""
        user = await self.get_user(user_id)

        if name is not None:
            user.name = name.strip()
        if role is not None:
            user.role = role
        if status is not None:
            user.status = status

        user.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        logger.info(f"Admin updated user {user_id}: name={name}, role={role}, status={status}")
        return user

    async def reset_user_password(self, user_id: UUID, new_password: str) -> User:
        """Reset a user's password (admin-only)."""
        user = await self.get_user(user_id)
        user.password_hash = hash_password(new_password)
        user.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)
        logger.info(f"Admin reset password for user {user_id}")
        return user

    async def delete_user(self, user_id: UUID, current_admin_id: UUID) -> bool:
        """Delete a user (cannot delete yourself)."""
        if user_id == current_admin_id:
            raise BadRequestException(detail="Cannot delete your own account")

        user = await self.get_user(user_id)
        await self.db.delete(user)
        await self.db.commit()
        logger.info(f"Admin deleted user {user_id}")
        return True

    # =========================================================================
    # Job Management (all users)
    # =========================================================================

    async def list_all_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        user_id: Optional[UUID] = None,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Tuple[List[dict], int]:
        """List jobs across all users with filtering."""
        query = (
            select(Job, User.email, User.name)
            .outerjoin(User, Job.user_id == User.id)
            .order_by(Job.created_at.desc())
        )
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

        total = await self.db.scalar(count_query) or 0

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        rows = result.all()

        jobs = []
        for row in rows:
            job = row[0]
            user_email = row[1]
            user_name = row[2]
            jobs.append({
                "id": str(job.id),
                "user_id": str(job.user_id) if job.user_id else None,
                "user_email": user_email,
                "user_name": user_name,
                "job_type": job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type),
                "status": job.status.value if hasattr(job.status, "value") else str(job.status),
                "progress_pct": job.progress_pct,
                "current_step": job.current_step,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.completed_at.isoformat() if job.completed_at else None,
            })

        return jobs, total
