"""
Utilities for moving retrieved documents across process boundaries.
"""

from typing import Any, Dict, List

from langchain_core.documents import Document

from .config import rag_config


def _make_json_safe(value: Any) -> Any:
    """Recursively convert metadata values into Celery JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _make_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]
    return str(value)


def serialize_documents(documents: List[Document]) -> List[Dict[str, Any]]:
    """Serialize LangChain documents into plain JSON-safe payloads."""
    return [
        {
            "page_content": document.page_content,
            "metadata": _make_json_safe(dict(document.metadata or {})),
        }
        for document in documents
    ]


def deserialize_documents(payload: List[Dict[str, Any]]) -> List[Document]:
    """Rehydrate LangChain documents from Celery-safe payloads."""
    documents: List[Document] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        documents.append(
            Document(
                page_content=str(item.get("page_content", "") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return documents


def format_context_documents(documents: List[Document]) -> str:
    """Render retrieved documents into the shared prompt context format."""
    if not documents:
        return ""

    context_parts = []
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "unknown")
        page = document.metadata.get("page", "?")
        context_parts.append(
            f"[Document {index}] (Source: {source}, Page: {page})\n{document.page_content}"
        )
    return "\n\n---\n\n".join(context_parts)


def extract_document_citations(documents: List[Document]) -> List[Dict[str, Any]]:
    """Build citation payloads from retrieved documents."""
    citations: List[Dict[str, Any]] = []
    for document in documents:
        citations.append(
            {
                "source": document.metadata.get("source", "unknown"),
                "page": document.metadata.get("page", 0) + 1,
                "filename": document.metadata.get("filename", ""),
                "file_hash": document.metadata.get("file_hash", ""),
                "snippet": document.page_content[:rag_config.SNIPPET_LENGTH] + "...",
            }
        )
    return citations
