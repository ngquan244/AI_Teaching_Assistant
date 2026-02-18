"""
Celery Application Configuration
================================
Central Celery app with queue routing, retry policies, and rate limiting.

This module should be imported as:
    from backend.celery_app import celery_app

Workers should be started with:
    celery -A backend.celery_app worker -Q rag -c 4 --loglevel=info
    celery -A backend.celery_app worker -Q llm -c 2 --loglevel=info
    celery -A backend.celery_app worker -Q canvas -c 2 --loglevel=info
    celery -A backend.celery_app worker -Q misc -c 4 --loglevel=info
"""
import os
import logging
from celery import Celery
from celery.signals import (
    task_prerun,
    task_postrun,
    task_failure,
    worker_ready,
)
from kombu import Queue, Exchange

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration from Environment
# =============================================================================

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")

# Rate limits from environment
LLM_RATE_LIMIT = os.getenv("LLM_RATE_LIMIT", "10/m")  # 10 requests per minute
CANVAS_RATE_LIMIT = os.getenv("CANVAS_RATE_LIMIT", "30/m")  # 30 requests per minute

# Worker concurrency defaults
WORKER_CONCURRENCY_RAG = int(os.getenv("WORKER_CONCURRENCY_RAG", "4"))
WORKER_CONCURRENCY_LLM = int(os.getenv("WORKER_CONCURRENCY_LLM", "2"))
WORKER_CONCURRENCY_CANVAS = int(os.getenv("WORKER_CONCURRENCY_CANVAS", "2"))
WORKER_CONCURRENCY_MISC = int(os.getenv("WORKER_CONCURRENCY_MISC", "4"))

# =============================================================================
# Queue Definitions
# =============================================================================

default_exchange = Exchange("default", type="direct")
rag_exchange = Exchange("rag", type="direct")
llm_exchange = Exchange("llm", type="direct")
canvas_exchange = Exchange("canvas", type="direct")
misc_exchange = Exchange("misc", type="direct")

CELERY_QUEUES = (
    Queue("default", default_exchange, routing_key="default"),
    Queue("rag", rag_exchange, routing_key="rag"),
    Queue("llm", llm_exchange, routing_key="llm"),
    Queue("canvas", canvas_exchange, routing_key="canvas"),
    Queue("misc", misc_exchange, routing_key="misc"),
)

# Task routing based on task name patterns
CELERY_ROUTES = {
    # RAG tasks
    "backend.tasks.rag_tasks.*": {"queue": "rag", "routing_key": "rag"},
    # LLM tasks
    "backend.tasks.llm_tasks.*": {"queue": "llm", "routing_key": "llm"},
    # Canvas tasks
    "backend.tasks.canvas_tasks.*": {"queue": "canvas", "routing_key": "canvas"},
    # Grading tasks (use misc queue)
    "backend.tasks.grading_tasks.*": {"queue": "misc", "routing_key": "misc"},
    # Misc tasks
    "backend.tasks.misc_tasks.*": {"queue": "misc", "routing_key": "misc"},
}

# =============================================================================
# Celery App Initialization
# =============================================================================

celery_app = Celery(
    "grader",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "backend.tasks.rag_tasks",
        "backend.tasks.llm_tasks",
        "backend.tasks.canvas_tasks",
        "backend.tasks.grading_tasks",
        "backend.tasks.misc_tasks",
    ],
)

# =============================================================================
# Celery Configuration
# =============================================================================

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Queue configuration
    task_queues=CELERY_QUEUES,
    task_routes=CELERY_ROUTES,
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
    
    # Result backend settings
    result_expires=86400,  # 24 hours
    result_extended=True,  # Store task name, args, kwargs in result
    
    # Task execution settings
    task_acks_late=True,  # Acknowledge after task completes (safer for retries)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # Prefetch one task at a time for fairness
    
    # Task time limits (in seconds)
    task_soft_time_limit=300,  # 5 minutes soft limit
    task_time_limit=600,  # 10 minutes hard limit
    
    # Retry policy defaults
    task_default_retry_delay=30,  # 30 seconds
    task_max_retries=5,
    
    # Rate limiting
    worker_state_db=None,  # Use memory for rate limiting state
    
    # Logging
    worker_hijack_root_logger=False,
    
    # Task tracking
    task_track_started=True,
    task_send_sent_event=True,
    
    # Beat scheduler (for periodic tasks if needed)
    beat_schedule={},
)

# =============================================================================
# Task Base Classes with Common Behaviors
# =============================================================================

from celery import Task
from typing import Optional, Any


class BaseTaskWithRetry(Task):
    """
    Base task class with standardized retry behavior and job tracking.
    """
    abstract = True
    
    # Retry settings (can be overridden per-task)
    autoretry_for = (Exception,)
    retry_backoff = True
    retry_backoff_max = 600  # Max backoff: 10 minutes
    retry_jitter = True
    max_retries = 5
    
    # Job tracking
    _job_id: Optional[str] = None
    
    def before_start(self, task_id, args, kwargs):
        """Called before task starts."""
        self._job_id = kwargs.get("job_id")
        if self._job_id:
            logger.info(f"Task {self.name}[{task_id}] starting for job_id={self._job_id}")
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        job_id = kwargs.get("job_id")
        if job_id:
            logger.info(f"Task {self.name}[{task_id}] succeeded for job_id={job_id}")
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails after all retries."""
        job_id = kwargs.get("job_id")
        if job_id:
            logger.error(
                f"Task {self.name}[{task_id}] failed for job_id={job_id}: {exc}",
                exc_info=einfo
            )
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Called when task is being retried."""
        job_id = kwargs.get("job_id")
        retry_count = self.request.retries
        if job_id:
            logger.warning(
                f"Task {self.name}[{task_id}] retry #{retry_count} for job_id={job_id}: {exc}"
            )


class RateLimitedLLMTask(BaseTaskWithRetry):
    """
    Task for LLM operations with rate limiting.
    """
    abstract = True
    rate_limit = LLM_RATE_LIMIT


class RateLimitedCanvasTask(BaseTaskWithRetry):
    """
    Task for Canvas API operations with rate limiting.
    """
    abstract = True
    rate_limit = CANVAS_RATE_LIMIT
    
    # Canvas-specific retry for transient errors
    autoretry_for = (Exception,)
    retry_backoff = True
    max_retries = 3


# =============================================================================
# Signal Handlers for Observability
# =============================================================================

@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Log when worker is ready."""
    logger.info(f"Celery worker ready: {sender}")


@task_prerun.connect
def task_prerun_handler(sender, task_id, task, args, kwargs, **other):
    """Log task start with correlation IDs."""
    job_id = kwargs.get("job_id", "N/A")
    user_id = kwargs.get("user_id", "N/A")
    logger.info(
        f"TASK_START | task={sender.name} | task_id={task_id} | "
        f"job_id={job_id} | user_id={user_id}"
    )


@task_postrun.connect
def task_postrun_handler(sender, task_id, task, args, kwargs, retval, state, **other):
    """Log task completion."""
    job_id = kwargs.get("job_id", "N/A")
    logger.info(
        f"TASK_END | task={sender.name} | task_id={task_id} | "
        f"job_id={job_id} | state={state}"
    )


@task_failure.connect
def task_failure_handler(sender, task_id, exception, args, kwargs, traceback, einfo, **other):
    """Log task failures with full context."""
    job_id = kwargs.get("job_id", "N/A")
    logger.error(
        f"TASK_FAILURE | task={sender.name} | task_id={task_id} | "
        f"job_id={job_id} | error={exception}",
        exc_info=True
    )


# =============================================================================
# Utility Functions
# =============================================================================

def get_task_info(task_id: str) -> dict:
    """
    Get information about a task by its ID.
    
    Args:
        task_id: Celery task ID
        
    Returns:
        Dict with task state, result, etc.
    """
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "state": result.state,
        "result": result.result if result.ready() else None,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None,
        "failed": result.failed() if result.ready() else None,
    }


def revoke_task(task_id: str, terminate: bool = False) -> bool:
    """
    Revoke a pending or running task.
    
    Args:
        task_id: Celery task ID
        terminate: If True, terminate running task (SIGTERM)
        
    Returns:
        True if revoke was sent
    """
    try:
        celery_app.control.revoke(task_id, terminate=terminate)
        logger.info(f"Revoked task {task_id}, terminate={terminate}")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke task {task_id}: {e}")
        return False
