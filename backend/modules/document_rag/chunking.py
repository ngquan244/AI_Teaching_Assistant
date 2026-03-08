"""
Document Chunking Module
========================
Split documents into chunks using RecursiveCharacterTextSplitter.
Parameters are taken from RAG_AI_Tutor.ipynb.
"""

import logging
from typing import List, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from .config import rag_config

logger = logging.getLogger(__name__)


def create_text_splitter(
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    separators: Optional[List[str]] = None
) -> RecursiveCharacterTextSplitter:
    """   
    Default parameters (from notebook):
    - chunk_size: 800
    - chunk_overlap: 100
    - separators: ["\n\n", "\n", ".", "!", "?", ",", " ", ""]
    
    Args:
        chunk_size: Maximum size of chunks (default from config)
        chunk_overlap: Overlap between chunks (default from config)
        separators: List of separators for splitting (default from config)
        
    Returns:
        Configured RecursiveCharacterTextSplitter
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size or rag_config.CHUNK_SIZE,
        chunk_overlap=chunk_overlap or rag_config.CHUNK_OVERLAP,
        separators=separators or rag_config.CHUNK_SEPARATORS,
        length_function=len,
        is_separator_regex=False,
    )


def chunk_documents(
    documents: List[Document],
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    separators: Optional[List[str]] = None,
    preserve_metadata: bool = True
) -> List[Document]:
    """
    Split documents into smaller chunks.
    
    Each chunk preserves the original document's metadata plus:
    - chunk_index: Index of chunk within the original document
    - chunk_total: Total number of chunks from the original document
    
    Args:
        documents: List of Document objects to split
        chunk_size: Maximum size of chunks
        chunk_overlap: Overlap between chunks
        separators: List of separators for splitting
        preserve_metadata: Whether to copy original metadata to chunks
        
    Returns:
        List of chunked Document objects
    """
    if not documents:
        logger.warning("No documents to chunk")
        return []
    
    logger.info(f"Chunking {len(documents)} documents with chunk_size={chunk_size or rag_config.CHUNK_SIZE}")
    
    # Create splitter
    text_splitter = create_text_splitter(chunk_size, chunk_overlap, separators)
    
    # Split documents
    chunks = text_splitter.split_documents(documents)
    
    # Add chunk-specific metadata
    if preserve_metadata:
        # Group chunks by source document
        source_chunks = {}
        for i, chunk in enumerate(chunks):
            source = chunk.metadata.get("source", "unknown")
            page = chunk.metadata.get("page", 0)
            key = f"{source}_{page}"
            
            if key not in source_chunks:
                source_chunks[key] = []
            source_chunks[key].append(i)
        
        # Add chunk indices
        for key, indices in source_chunks.items():
            for chunk_idx, doc_idx in enumerate(indices):
                chunks[doc_idx].metadata["chunk_index"] = chunk_idx
                chunks[doc_idx].metadata["chunk_total"] = len(indices)
    
    logger.info(f"Created {len(chunks)} chunks from {len(documents)} documents")
    
    return chunks


def chunk_text(
    text: str,
    metadata: Optional[dict] = None,
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None
) -> List[Document]:
    """
    Chunk a plain text string into Documents.
    
    Args:
        text: Text to chunk
        metadata: Optional metadata to add to all chunks
        chunk_size: Maximum size of chunks
        chunk_overlap: Overlap between chunks
        
    Returns:
        List of Document objects
    """
    if not text or not text.strip():
        return []
    
    # Create a single document from text
    doc = Document(
        page_content=text,
        metadata=metadata or {}
    )
    
    # Chunk it
    return chunk_documents(
        [doc],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap
    )
