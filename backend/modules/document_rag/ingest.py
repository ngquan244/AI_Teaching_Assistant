"""
Document Ingestion Module
=========================
Load PDF documents using PyMuPDF (fitz) — a C-binding parser that is
~10× faster than PyPDFLoader for typical text PDFs. Falls back to the
pure-Python ``PyPDFLoader`` if PyMuPDF is unavailable or fails on a
specific file (e.g. corrupt / unusual encoding).
"""

import os
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Probe PyMuPDF once at import time so the hot path stays branch-free.
try:
    import pymupdf as _fitz  # type: ignore
    _PYMUPDF_AVAILABLE = True
except Exception as _pymupdf_import_err:  # pragma: no cover - depends on env
    _fitz = None  # type: ignore[assignment]
    _PYMUPDF_AVAILABLE = False
    logger.warning(
        "PyMuPDF not available, falling back to PyPDFLoader: %s",
        _pymupdf_import_err,
    )


def compute_file_hash(file_path: str) -> str:
    """
    Compute MD5 hash of a file for deduplication.
    
    Args:
        file_path: Path to the file
        
    Returns:
        MD5 hash string
    """
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def get_file_metadata(file_path: str) -> Dict[str, Any]:
    """
    Get file metadata for tracking.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with file metadata
    """
    path = Path(file_path)
    stat = path.stat()
    
    return {
        "filename": path.name,
        "file_path": str(path.absolute()),
        "file_size": stat.st_size,
        "file_hash": compute_file_hash(file_path),
        "modified_time": stat.st_mtime,
    }


def _load_pdf_with_pymupdf(path: Path) -> List[Document]:
    """Extract one ``Document`` per page using PyMuPDF.

    Page metadata mirrors what ``PyPDFLoader`` produces (``source`` + 0-indexed
    ``page``) so downstream code (chunker, retriever, citation rendering) needs
    no changes. Empty pages are kept as zero-length docs to preserve page
    indexing — the chunker filters them naturally.
    """
    if _fitz is None:  # pragma: no cover - guarded by caller
        raise RuntimeError("PyMuPDF is not available")
    docs: List[Document] = []
    src = str(path)
    with _fitz.open(src) as pdf:
        for page_idx, page in enumerate(pdf):
            try:
                text = page.get_text("text") or ""
            except Exception as page_err:
                logger.warning(
                    "PyMuPDF: page %d of %s failed text extract: %s",
                    page_idx, path.name, page_err,
                )
                text = ""
            docs.append(
                Document(
                    page_content=text,
                    metadata={"source": src, "page": page_idx},
                )
            )
    return docs


def _load_pdf_pages(path: Path) -> List[Document]:
    """Load PDF pages, preferring PyMuPDF and falling back to PyPDFLoader.

    The fallback only triggers when PyMuPDF raises (corrupt file, unsupported
    feature, etc.) — not when it merely returns no text, since a legitimately
    image-only PDF would silently regress to the slower path otherwise.
    """
    if _PYMUPDF_AVAILABLE:
        try:
            return _load_pdf_with_pymupdf(path)
        except Exception as exc:
            logger.warning(
                "PyMuPDF failed for %s, falling back to PyPDFLoader: %s",
                path.name, exc,
            )
    loader = PyPDFLoader(str(path))
    return loader.load()


def load_pdf_documents(
    file_path: str,
    add_file_metadata: bool = True
) -> List[Document]:
    """
    Load PDF file and return list of Document objects.
    
    Each page becomes a Document with metadata including:
    - source: original file path
    - page: page number (0-indexed)
    - file_hash: MD5 hash for deduplication
    
    Args:
        file_path: Path to PDF file
        add_file_metadata: Whether to add extended file metadata
        
    Returns:
        List of Document objects, one per page
        
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not a PDF
    """
    # Validate file
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"File is not a PDF: {file_path}")
    
    logger.debug(f"Loading PDF: {file_path}")

    documents = _load_pdf_pages(path)

    logger.debug(f"Loaded {len(documents)} pages from PDF")
    
    # Add extended metadata for deduplication
    if add_file_metadata:
        file_meta = get_file_metadata(file_path)
        for doc in documents:
            doc.metadata.update({
                "file_hash": file_meta["file_hash"],
                "filename": file_meta["filename"],
                "file_size": file_meta["file_size"],
            })
            # Generate unique doc_id for each page
            page_num = doc.metadata.get("page", 0)
            doc.metadata["doc_id"] = f"{file_meta['file_hash']}_{page_num}"
    
    return documents


def load_multiple_pdfs(
    file_paths: List[str],
    add_file_metadata: bool = True
) -> List[Document]:
    """
    Load multiple PDF files.
    
    Args:
        file_paths: List of paths to PDF files
        add_file_metadata: Whether to add extended file metadata
        
    Returns:
        Combined list of Document objects from all files
    """
    all_documents = []
    
    for file_path in file_paths:
        try:
            docs = load_pdf_documents(file_path, add_file_metadata)
            all_documents.extend(docs)
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            raise
    
    logger.info(f"Total documents loaded: {len(all_documents)}")
    return all_documents
