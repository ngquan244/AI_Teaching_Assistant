"""
Backend Tasks Package
=====================
Celery task modules organized by domain.

Queues:
- rag: Document ingestion, indexing, retrieval
- llm: Quiz generation, chat, topic extraction
- canvas: Canvas API operations
- misc: Grading, file operations, etc.
"""

from backend.tasks import rag_tasks
from backend.tasks import llm_tasks
from backend.tasks import canvas_tasks
from backend.tasks import grading_tasks
from backend.tasks import misc_tasks

__all__ = [
    "rag_tasks",
    "llm_tasks",
    "canvas_tasks",
    "grading_tasks",
    "misc_tasks",
]
