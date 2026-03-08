"""
Document Ingestion Module
=========================
Load PDF documents using PyPDFLoader.
"""

import os
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


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
    
    # Load with PyPDFLoader
    loader = PyPDFLoader(str(file_path))
    documents = loader.load()
    
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
