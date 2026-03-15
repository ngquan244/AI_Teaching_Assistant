"""
Backend Tasks Package
=====================
Celery task modules organized by domain.

Queues:
- rag: Document ingestion, indexing, retrieval
- llm: Quiz generation, topic extraction
- canvas: Canvas API operations
"""

from backend.tasks import rag_tasks
from backend.tasks import llm_tasks
from backend.tasks import canvas_tasks

__all__ = [
    "rag_tasks",
    "llm_tasks",
    "canvas_tasks",
]
