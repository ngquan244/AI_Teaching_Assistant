"""
Canvas RAG Service Module
=========================
Service for Canvas-sourced documents with separate storage, deduplication,
and per-file ChromaDB collections for concurrent multi-user indexing.

Key architecture change: Uses per-file collections instead of a single global
collection to eliminate write lock contention between users.
"""

import os
import uuid as _uuid
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

import httpx
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from .config import rag_config
from .ingest import load_pdf_documents, get_file_metadata
from .chunking import chunk_documents
from .vectorstore import ChromaVectorStore
from .collection_manager import (
    PerFileCollectionManager,
    get_canvas_collection_manager,
    CollectionNameGenerator
)
from .retriever import DocumentRetriever, MultiCollectionRetriever
from .rag_chain import RAGChain
from .quiz_generator import QuizGenerator
from .llm_providers import BaseLLM, LLMFactory
from .rag_repository import SyncRAGCollectionRepository
from backend.database.models.rag_document import RAGSourceType
from backend.core.logger import quiz_logger, canvas_logger

logger = canvas_logger


class CanvasTopicStorage:
    """
    Persistent storage for Canvas document topics.
    Completely separate from uploaded document topics.
    """
    
    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self.storage_file = self.storage_dir / "canvas_document_topics.json"
        self._topics: Dict[str, Dict[str, Any]] = {}
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._load()
    
    def _load(self):
        try:
            if self.storage_file.exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    self._topics = json.load(f)
                logger.info(f"Loaded Canvas topics for {len(self._topics)} documents")
        except Exception as e:
            logger.warning(f"Could not load Canvas topics: {e}")
            self._topics = {}
    
    def _save(self):
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self._topics, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Could not save Canvas topics: {e}")
    
    def save_topics(self, file_hash: str, filename: str, topics: List[Dict[str, str]]):
        self._topics[file_hash] = {
            "filename": filename,
            "topics": topics,
            "extracted_at": datetime.now().isoformat()
        }
        self._save()
    
    def get_topics(self, file_hash: str) -> Optional[List[Dict[str, str]]]:
        if file_hash in self._topics:
            return self._topics[file_hash].get("topics", [])
        return None
    
    def get_topics_by_filename(self, filename: str) -> Optional[List[Dict[str, str]]]:
        logger.info(f"Looking for topics with filename: {filename}")
        logger.info(f"Available files in topics: {[d.get('filename') for h, d in self._topics.items()]}")
        for file_hash, data in self._topics.items():
            if data.get("filename") == filename:
                topics = data.get("topics", [])
                logger.info(f"Found {len(topics)} topics for {filename}")
                return topics
        logger.info(f"No topics found for {filename}")
        return None
    
    def has_topics(self, file_hash: str) -> bool:
        return file_hash in self._topics
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        documents = []
        for file_hash, data in self._topics.items():
            documents.append({
                "file_hash": file_hash,
                "filename": data.get("filename", "unknown"),
                "topic_count": len(data.get("topics", [])),
                "extracted_at": data.get("extracted_at")
            })
        return documents
    
    def remove_document(self, file_hash: str) -> bool:
        if file_hash in self._topics:
            del self._topics[file_hash]
            self._save()
            return True
        return False
    
    def update_topics_by_filename(self, filename: str, topics: List[Dict[str, str]]) -> bool:
        for file_hash, data in self._topics.items():
            if data.get("filename") == filename:
                self._topics[file_hash]["topics"] = topics
                self._topics[file_hash]["updated_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False
    
    def clear(self):
        self._topics = {}
        self._save()


class CanvasRAGService:
    """
    RAG Service specifically for Canvas-sourced documents.
    
    Uses per-file ChromaDB collections to enable concurrent multi-user indexing.
    Each file gets its own collection named like 'canvas_{course_id}_{file_hash}'.
    """
    
    _instance: Optional["CanvasRAGService"] = None
    
    # Canvas-specific paths
    CANVAS_RAG_DIR = Path("./data/canvas_rag_uploads")
    CANVAS_CHROMA_DIR = Path("./data/chroma/canvas_document_rag")
    CANVAS_COLLECTION_NAME = "canvas_document_rag_collection"  # Legacy, deprecated
    
    def __init__(self):
        # Ensure base directories exist
        self.CANVAS_RAG_DIR.mkdir(parents=True, exist_ok=True)
        self.CANVAS_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Legacy shared registries (for migration only)
        self.md5_registry_file = self.CANVAS_RAG_DIR / ".md5_registry.json"
        self.indexed_files_registry = self.CANVAS_RAG_DIR / ".indexed_files.json"
        
        logger.info("Initializing Canvas RAG Service with per-file collections...")
        logger.info(f"Canvas RAG directory: {self.CANVAS_RAG_DIR}")
        logger.info(f"Canvas Chroma directory: {self.CANVAS_CHROMA_DIR}")
        
        # Per-file collection manager (replaces global vectorstore)
        self._collection_manager: Optional[PerFileCollectionManager] = None
        
        # Legacy support - will be deprecated
        self._vector_store: Optional[ChromaVectorStore] = None
        
        # Multi-collection retriever for querying across files
        self._multi_retriever: Optional[MultiCollectionRetriever] = None
        self._rag_chain: Optional[RAGChain] = None
        self._quiz_generator: Optional[QuizGenerator] = None
        self._llm_provider: Optional[BaseLLM] = None
        self._topic_storage: Optional[CanvasTopicStorage] = None
        
        self._initialized = False
    
    def _ensure_initialized(self):
        if self._initialized:
            return
        
        logger.info("Initializing Canvas RAG components with per-file collection manager...")
        
        # Initialize per-file collection manager for Canvas files
        self._collection_manager = get_canvas_collection_manager()
        
        # Legacy vector store for backwards compatibility
        try:
            self._vector_store = ChromaVectorStore(
                persist_directory=str(self.CANVAS_CHROMA_DIR),
                collection_name=self.CANVAS_COLLECTION_NAME
            )
        except Exception as e:
            logger.warning(f"Could not initialize legacy Canvas vectorstore: {e}")
            self._vector_store = None
        
        # Initialize LLM provider
        self._llm_provider = LLMFactory.create()
        
        # Initialize multi-collection retriever
        self._multi_retriever = MultiCollectionRetriever(
            collection_manager=self._collection_manager,
            llm_provider=self._llm_provider
        )
        
        self._rag_chain = RAGChain(
            retriever=self._multi_retriever,
            llm_provider=self._llm_provider
        )
        
        self._quiz_generator = QuizGenerator(
            retriever=self._multi_retriever,
            llm_provider=self._llm_provider
        )
        
        self._topic_storage = CanvasTopicStorage(str(self.CANVAS_RAG_DIR))
        
        self._initialized = True
        logger.info("Canvas RAG Service initialized with per-file collections")
    
    @classmethod
    def get_instance(cls) -> "CanvasRAGService":
        if cls._instance is None:
            cls._instance = CanvasRAGService()
        return cls._instance
    
    # ===== Per-user directory helpers =====
    
    def _get_user_dir(self, user_id: str) -> Path:
        """Get per-user Canvas RAG directory, creating if needed."""
        user_dir = self.CANVAS_RAG_DIR / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _get_user_md5_registry_file(self, user_id: str) -> Path:
        return self._get_user_dir(user_id) / ".md5_registry.json"
    
    def _get_user_indexed_registry_file(self, user_id: str) -> Path:
        return self._get_user_dir(user_id) / ".indexed_files.json"
    
    # ===== MD5 Deduplication =====
    
    def _load_md5_registry(self, user_id: Optional[str] = None) -> Dict[str, str]:
        """Load MD5 registry for Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_md5_registry_file(user_id) if user_id else self.md5_registry_file
        if registry_file.exists():
            try:
                with open(registry_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load Canvas MD5 registry: {e}")
        return {}
    
    def _save_md5_registry(self, registry: Dict[str, str], user_id: Optional[str] = None):
        """Save MD5 registry for Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_md5_registry_file(user_id) if user_id else self.md5_registry_file
        try:
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save Canvas MD5 registry: {e}")
    
    def _compute_md5(self, content: bytes) -> str:
        return hashlib.md5(content).hexdigest()
    
    def _check_duplicate(self, md5_hash: str, user_id: Optional[str] = None) -> Optional[str]:
        """Check if file with same MD5 exists, return existing filename if so"""
        registry = self._load_md5_registry(user_id)
        return registry.get(md5_hash)
    
    # ===== Indexed Files Registry =====
    
    def _load_indexed_registry(self, user_id: Optional[str] = None) -> Dict[str, Dict]:
        """Load registry of indexed Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_indexed_registry_file(user_id) if user_id else self.indexed_files_registry
        if registry_file.exists():
            try:
                with open(registry_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load indexed files registry: {e}")
        return {}
    
    def _save_indexed_registry(self, registry: Dict[str, Dict], user_id: Optional[str] = None):
        """Save registry of indexed Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_indexed_registry_file(user_id) if user_id else self.indexed_files_registry
        try:
            with open(registry_file, 'w') as f:
                json.dump(registry, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save indexed files registry: {e}")
    
    # ===== Download and Index =====
    
    async def download_file(
        self,
        url: str,
        filename: str,
        course_id: int,
        file_id: int,
        canvas_token: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Download file from Canvas with MD5 deduplication.
        Returns status: saved, duplicate, or failed.
        Files are stored in per-user subdirectories.
        """
        try:
            # Determine target directory (per-user or legacy shared)
            target_dir = self._get_user_dir(user_id) if user_id else self.CANVAS_RAG_DIR
            
            # Build headers with Canvas token for authentication
            headers = {}
            if canvas_token:
                headers["Authorization"] = f"Bearer {canvas_token}"
            
            async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                content = response.content
            
            # Compute MD5
            md5_hash = self._compute_md5(content)
            
            # Check duplicate (per-user)
            existing = self._check_duplicate(md5_hash, user_id)
            if existing:
                return {
                    "success": True,
                    "status": "duplicate",
                    "md5_hash": md5_hash,
                    "existing_filename": existing,
                    "message": f"File already exists as: {existing}"
                }
            
            # Sanitize and save
            safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
            if not safe_filename:
                safe_filename = f"canvas_{file_id}.pdf"
            if not safe_filename.lower().endswith('.pdf'):
                safe_filename += '.pdf'
            
            file_path = target_dir / safe_filename
            counter = 1
            base_name = file_path.stem
            while file_path.exists():
                file_path = target_dir / f"{base_name}_{counter}.pdf"
                counter += 1
            
            with open(file_path, 'wb') as f:
                f.write(content)
            
            # Update MD5 registry (per-user)
            registry = self._load_md5_registry(user_id)
            registry[md5_hash] = file_path.name
            self._save_md5_registry(registry, user_id)
            
            return {
                "success": True,
                "status": "saved",
                "md5_hash": md5_hash,
                "filename": file_path.name,
                "file_path": str(file_path),
                "message": f"File saved: {file_path.name}"
            }
            
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "status": "failed",
                "error": f"HTTP error: {e.response.status_code}"
            }
        except Exception as e:
            logger.error(f"Error downloading Canvas file: {e}")
            return {
                "success": False,
                "status": "failed",
                "error": str(e)
            }
    
    def ingest_document(
        self,
        file_path: str,
        extract_topics: bool = True,
        course_id: Optional[int] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Ingest a Canvas PDF document into a per-file collection.
        
        Args:
            file_path: Path to the PDF file
            extract_topics: Whether to extract topics after indexing
            course_id: Canvas course ID for collection naming
            user_id: User ID for per-user scoping
            db_session: Sync DB session for metadata persistence
        """
        self._ensure_initialized()
        
        logger.info(f"Ingesting Canvas document into per-file collection: {file_path}")
        
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"File not found: {file_path}",
                    "chunks_added": 0
                }
            
            # Get file metadata
            file_meta = get_file_metadata(file_path)
            file_hash = file_meta["file_hash"]
            filename = file_meta["filename"]
            
            # Check if already indexed using per-file collection manager
            if self._collection_manager.is_indexed(file_hash):
                logger.info(f"Canvas document already indexed in per-file collection: {file_path}")
                
                collection_name = self._collection_manager.get_collection_name(file_hash, course_id)
                has_topics = self._topic_storage.has_topics(file_hash)
                topics_extracted = []
                
                # If already indexed but no topics, extract them now
                if extract_topics and not has_topics:
                    logger.info(f"Extracting topics for already indexed document: {file_path}")
                    try:
                        topics_extracted = self._extract_and_save_topics(
                            file_hash=file_hash,
                            filename=filename
                        )
                        has_topics = len(topics_extracted) > 0
                    except Exception as e:
                        logger.warning(f"Failed to extract topics for indexed doc: {e}")
                
                return {
                    "success": True,
                    "message": "Document already indexed",
                    "file_hash": file_hash,
                    "filename": filename,
                    "collection_name": collection_name,
                    "chunks_added": 0,
                    "already_indexed": True,
                    "has_topics": has_topics,
                    "topics_extracted": len(topics_extracted),
                    "topics": topics_extracted
                }
            
            # Load PDF
            documents = load_pdf_documents(file_path)
            
            if not documents:
                return {
                    "success": False,
                    "error": "No content extracted from PDF",
                    "chunks_added": 0
                }
            
            # Chunk documents
            chunks = chunk_documents(documents)
            
            # Add to per-file Canvas collection (NOT global collection)
            # This is the key change that enables concurrent indexing
            added_count = self._collection_manager.add_documents(
                file_hash=file_hash,
                filename=filename,
                documents=chunks,
                course_id=course_id,
                replace_existing=True  # Idempotent: re-indexing replaces old data
            )
            
            collection_name = self._collection_manager.get_collection_name(file_hash, course_id)
            logger.info(f"Successfully ingested {added_count} chunks from Canvas file into collection: {collection_name}")
            
            # Extract and save topics (pass chunks directly for efficiency)
            topics_extracted = []
            if extract_topics and added_count > 0:
                try:
                    topics_extracted = self._extract_and_save_topics(
                        file_hash=file_hash,
                        filename=filename,
                        chunks=chunks
                    )
                except Exception as e:
                    logger.warning(f"Failed to extract topics: {e}")
            
            # Update indexed files registry (per-user)
            indexed_registry = self._load_indexed_registry(user_id)
            indexed_registry[file_hash] = {
                "filename": filename,
                "file_path": file_path,
                "collection_name": collection_name,
                "course_id": course_id,
                "indexed_at": datetime.now().isoformat(),
                "chunks_added": added_count,
                "topic_count": len(topics_extracted)
            }
            self._save_indexed_registry(indexed_registry, user_id)
            
            # ---- Persist to PostgreSQL when session available ----
            col_row = None
            if db_session and user_id:
                try:
                    col_row = SyncRAGCollectionRepository.register(
                        db_session,
                        user_id=_uuid.UUID(user_id),
                        file_hash=file_hash,
                        filename=filename,
                        collection_name=collection_name or f"canvas_{file_hash[:16]}",
                        source=RAGSourceType.CANVAS,
                        course_id=int(course_id) if course_id else None,
                        chunk_count=added_count,
                        is_indexed=True,
                    )
                    if topics_extracted and col_row:
                        SyncRAGCollectionRepository.save_topics(
                            db_session,
                            collection_id=col_row.id,
                            topics=topics_extracted,
                        )
                    db_session.commit()
                except Exception as e:
                    logger.warning(f"Could not persist to PostgreSQL: {e}")
                    db_session.rollback()
            
            return {
                "success": True,
                "message": f"Successfully indexed {added_count} chunks into per-file collection",
                "file_hash": file_hash,
                "filename": file_meta["filename"],
                "pages_loaded": len(documents),
                "chunks_added": added_count,
                "already_indexed": False,
                "topics_extracted": len(topics_extracted),
                "topics": topics_extracted
            }
            
        except Exception as e:
            logger.error(f"Error ingesting Canvas document: {e}")
            return {
                "success": False,
                "error": str(e),
                "chunks_added": 0
            }
    
    def _extract_and_save_topics(
        self,
        file_hash: str,
        filename: str,
        num_topics: int = 10,
        chunks: Optional[List[Document]] = None,
        course_id: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """Extract topics from document and save to Canvas topic storage.
        
        Args:
            file_hash: Hash of the file
            filename: Name of the file
            num_topics: Number of topics to extract
            chunks: Pre-loaded chunks (optional, used during indexing)
            course_id: Canvas course ID for collection lookup
        """
        try:
            # If chunks not provided, get from per-file collection
            if chunks is None:
                try:
                    # Query the per-file collection for this document
                    docs = self._collection_manager.query_collection(
                        file_hash=file_hash,
                        query="main topics content overview",  # Generic query to get content
                        k=15,
                        course_id=course_id
                    )
                    logger.info(f"Got {len(docs)} documents from per-file collection")
                except Exception as e:
                    logger.warning(f"Could not get chunks from per-file collection: {e}")
                    docs = []
            else:
                docs = chunks[:15]
            
            logger.info(f"Total docs for topic extraction: {len(docs)}")
            
            if not docs:
                logger.warning(f"No docs found for topic extraction, file_hash: {file_hash}")
                return []
            
            # Combine content for topic extraction
            combined_content = "\n\n".join([doc.page_content for doc in docs[:10]])
            
            # Use LLM to extract topics
            prompt = f"""Dựa trên nội dung tài liệu sau, hãy liệt kê {num_topics} chủ đề chính.
Chỉ trả về danh sách các chủ đề, mỗi chủ đề trên một dòng.
Mỗi chủ đề nên ngắn gọn (3-6 từ).

Nội dung tài liệu:
{combined_content[:8000]}

Danh sách {num_topics} chủ đề chính (mỗi dòng một chủ đề):"""

            # Use invoke method (not generate)
            response_msg = self._llm_provider.invoke(prompt)
            response = response_msg.content if hasattr(response_msg, 'content') else str(response_msg)
            
            logger.info(f"LLM response for topics: {response[:200]}...")
            
            # Parse topics
            lines = response.strip().split('\n')
            topics = []
            for line in lines:
                cleaned = line.strip().lstrip('0123456789.-) ').strip()
                if cleaned and len(cleaned) > 2:
                    topics.append({
                        "name": cleaned,
                        "description": ""
                    })
            
            topics = topics[:num_topics]
            
            logger.info(f"Extracted {len(topics)} topics for {filename}")
            
            # Save to Canvas topic storage
            if topics:
                self._topic_storage.save_topics(file_hash, filename, topics)
            
            return topics
            
        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return []
    
    def extract_topics_for_file(self, filename: str, num_topics: int = 10, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Extract topics for a specific file by filename."""
        self._ensure_initialized()
        
        # Find file hash from indexed registry (per-user)
        indexed_registry = self._load_indexed_registry(user_id)
        file_hash = None
        for hash_val, data in indexed_registry.items():
            if data.get("filename") == filename:
                file_hash = hash_val
                break
        
        if not file_hash:
            return {
                "success": False,
                "error": f"File not indexed: {filename}"
            }
        
        try:
            topics = self._extract_and_save_topics(file_hash, filename, num_topics)
            return {
                "success": True,
                "topics": [t["name"] for t in topics],
                "filename": filename
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    # ===== Topic Management =====
    
    def get_document_topics(
        self,
        filename: str,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Get topics for a Canvas document."""
        self._ensure_initialized()
        
        topics = None
        if db_session and user_id:
            try:
                topics = SyncRAGCollectionRepository.get_topics_by_filename(
                    db_session, filename, _uuid.UUID(user_id),
                )
            except Exception as e:
                logger.warning(f"DB query failed for get_document_topics, falling back to legacy: {e}")
                db_session.rollback()
        if topics is None:
            raw = self._topic_storage.get_topics_by_filename(filename)
            if raw:
                topics = raw
        
        if topics:
            # Normalise to list of strings for Canvas API compatibility
            names = [t["name"] if isinstance(t, dict) else t for t in topics]
            return {
                "success": True,
                "topics": names,
                "filename": filename
            }
        return {
            "success": True,
            "topics": [],
            "filename": filename
        }
    
    def update_document_topics(
        self,
        filename: str,
        topics: List[str],
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Update topics for a Canvas document."""
        self._ensure_initialized()
        
        topic_dicts = [{"name": t, "description": ""} for t in topics]
        
        success = False
        if db_session and user_id:
            try:
                success = SyncRAGCollectionRepository.update_topics_by_filename(
                    db_session, filename, topic_dicts, _uuid.UUID(user_id),
                )
            except Exception as e:
                logger.warning(f"DB query failed for update_document_topics, falling back to legacy: {e}")
                db_session.rollback()
        if not success:
            success = self._topic_storage.update_topics_by_filename(filename, topic_dicts)
        
        return {
            "success": success,
            "message": "Topics updated" if success else "Document not found"
        }
    
    # ===== List and Stats =====
    
    def list_indexed_documents(
        self,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """List all indexed Canvas documents."""
        self._ensure_initialized()
        
        # ---- DB-backed path ----
        db_documents = []
        db_seen_hashes = set()
        if db_session and user_id:
            try:
                rows = SyncRAGCollectionRepository.get_all_documents_with_topics(
                    db_session, _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
                for r in rows:
                    db_documents.append({
                        "filename": r["filename"],
                        "original_filename": r["filename"],
                        "file_hash": r["file_hash"],
                        "indexed_at": r.get("indexed_at"),
                        "chunks_added": r.get("chunk_count", 0),
                        "topic_count": r.get("topic_count", 0),
                        "course_id": r.get("course_id"),
                    })
                    db_seen_hashes.add(r["file_hash"])
            except Exception as e:
                logger.warning(f"DB query failed for list_indexed_documents, falling back to legacy: {e}")
                db_session.rollback()
        
        documents = list(db_documents)
        seen_hashes = set(db_seen_hashes)
        
        # Source 1: Get from indexed_files_registry (per-user)
        indexed_registry = self._load_indexed_registry(user_id)
        for file_hash, data in indexed_registry.items():
            if file_hash in seen_hashes:
                continue
            filename = data.get("filename", "unknown")
            topics = self._topic_storage.get_topics(file_hash) or []
            documents.append({
                "filename": filename,
                "original_filename": filename,
                "file_hash": file_hash,
                "indexed_at": data.get("indexed_at"),
                "chunks_added": data.get("chunks_added", 0),
                "topic_count": len(topics),
                "course_id": data.get("course_id")
            })
            seen_hashes.add(file_hash)
        
        # Source 2: Get from collection_manager (per-file collections)
        # This catches files indexed via collection_manager but not in indexed_registry
        try:
            indexed_files = self._collection_manager.get_indexed_files()
            for file_info in indexed_files:
                file_hash = file_info.get("file_hash")
                if file_hash and file_hash not in seen_hashes:
                    filename = file_info.get("filename", "unknown")
                    topics = self._topic_storage.get_topics(file_hash) or []
                    documents.append({
                        "filename": filename,
                        "original_filename": filename,
                        "file_hash": file_hash,
                        "indexed_at": file_info.get("indexed_at"),
                        "chunks_added": file_info.get("chunk_count", 0),
                        "topic_count": len(topics),
                        "course_id": file_info.get("course_id")
                    })
        except Exception as e:
            logger.warning(f"Could not get files from collection_manager: {e}")
        
        return {
            "success": True,
            "documents": documents,
            "count": len(documents)
        }
    
    def list_downloaded_files(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """List downloaded Canvas files for a specific user."""
        self._ensure_initialized()
        
        try:
            files = []
            indexed_registry = self._load_indexed_registry(user_id)
            
            # Also get indexed files from collection_manager
            collection_indexed_files = set()
            try:
                for file_info in self._collection_manager.get_indexed_files():
                    collection_indexed_files.add(file_info.get("filename", ""))
            except Exception as e:
                logger.warning(f"Could not get collection manager files: {e}")
            
            # Scope to per-user directory
            target_dir = self._get_user_dir(user_id) if user_id else self.CANVAS_RAG_DIR
            
            for file_path in target_dir.glob("*.pdf"):
                stat = file_path.stat()
                
                # Check if indexed from both sources
                is_indexed_registry = any(
                    d.get("filename") == file_path.name 
                    for d in indexed_registry.values()
                )
                is_indexed_collection = file_path.name in collection_indexed_files
                is_indexed = is_indexed_registry or is_indexed_collection
                
                files.append({
                    "filename": file_path.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "is_indexed": is_indexed
                })
            
            return {
                "success": True,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            logger.error(f"Error listing Canvas files: {e}")
            return {
                "success": False,
                "error": str(e),
                "files": []
            }
    
    def get_index_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """Get Canvas index statistics for a specific user."""
        self._ensure_initialized()
        
        try:
            stats = self._vector_store.get_collection_stats()
            indexed_registry = self._load_indexed_registry(user_id)
            
            return {
                "total_documents": len(indexed_registry),
                "total_chunks": stats.get("total_documents", 0),
                "collection_name": self.CANVAS_COLLECTION_NAME,
                "unique_files": len(indexed_registry)
            }
        except Exception as e:
            logger.error(f"Error getting Canvas stats: {e}")
            return {
                "total_documents": 0,
                "total_chunks": 0,
                "collection_name": self.CANVAS_COLLECTION_NAME,
                "unique_files": 0,
                "error": str(e)
            }
    
    def query(
        self,
        question: str,
        k: int = 6,
        return_context: bool = False,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Query the Canvas document knowledge base."""
        self._ensure_initialized()
        return self._rag_chain.query(question, k=k, return_context=return_context)
    
    def generate_quiz(
        self,
        topics: List[str],
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "vi",
        k: int = 10,
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Generate quiz from Canvas documents."""
        self._ensure_initialized()
        
        if not topics or len(topics) == 0:
            return {
                "success": False,
                "questions": [],
                "error": "Cần có ít nhất một chủ đề để tạo quiz"
            }
        
        logger.info(f"Generating Canvas quiz: topics={topics}, num_questions={num_questions}")
        quiz_logger.info(f"canvas generate_quiz called: selected_documents={selected_documents}, user_id={user_id}, db_session={'present' if db_session else 'None'}")
        
        try:
            # CRITICAL: Always reload registry from disk before retrieval.
            # In multi-process Docker (backend + worker-llm), the backend process
            # updates the registry JSON after ingest, but this worker's in-memory
            # registry is stale from startup. Without reload, query_collection()
            # falls back to generating wrong collection name (doc_* instead of
            # canvas_*), pointing to an empty/nonexistent Chroma → 0 docs.
            self._collection_manager.ensure_fresh_state()

            # Resolve target file hashes from selected_documents
            # Canvas collections are registered WITHOUT user_id (user_id=null),
            # so we must NOT filter by user_id in registry lookups.
            target_hashes = None
            if selected_documents:
                target_hashes = []
                if db_session and user_id:
                    try:
                        rows = SyncRAGCollectionRepository.get_by_filenames(
                            db_session, selected_documents, _uuid.UUID(user_id),
                            source=RAGSourceType.CANVAS,
                        )
                        target_hashes = [r.file_hash for r in rows]
                        quiz_logger.info(f"Canvas DB get_by_filenames: {len(rows)} rows: {[(r.filename, r.file_hash[:8]) for r in rows]}")
                    except Exception as e:
                        logger.warning(f"Canvas DB get_by_filenames failed: {e}")
                        quiz_logger.warning(f"Canvas DB get_by_filenames failed: {e}")
                        db_session.rollback()
                # Fallback to in-memory registry (no user_id filter — canvas entries have user_id=null)
                if not target_hashes:
                    matching = self._collection_manager.registry.get_by_filenames(selected_documents)
                    target_hashes = [m.file_hash for m in matching]
                    quiz_logger.info(f"Canvas registry fallback: matched {len(matching)} of {len(selected_documents)} docs: {[(m.filename, m.file_hash[:8]) for m in matching]}")
                quiz_logger.info(f"Canvas resolved {len(target_hashes)} hashes from {len(selected_documents)} docs: {selected_documents} -> {[h[:8] for h in target_hashes]}")
            else:
                quiz_logger.warning(f"canvas selected_documents is None/empty ({selected_documents!r}) — will query ALL collections!")

            n_resolved = len(target_hashes) if target_hashes is not None else 'all'

            # If multiple topics, use the multi-topic method
            if len(topics) > 1:
                result = self._quiz_generator.generate_quiz_multi_topics(
                    topics=topics,
                    num_questions=num_questions,
                    difficulty=difficulty,
                    language=language,
                    k=k,
                    target_file_hashes=target_hashes,
                    user_id=user_id
                )
            else:
                # Single topic
                result = self._quiz_generator.generate_quiz(
                    topic=topics[0],
                    num_questions=num_questions,
                    difficulty=difficulty,
                    language=language,
                    k=k,
                    target_file_hashes=target_hashes,
                    user_id=user_id
                )
            
            result["_resolved_hashes"] = n_resolved
            return result
            
        except Exception as e:
            logger.error(f"Error generating Canvas quiz: {e}")
            return {
                "success": False,
                "questions": [],
                "error": f"Lỗi khi tạo quiz: {str(e)}"
            }
    
    def reset_index(self) -> Dict[str, Any]:
        """Reset Canvas index and clear all data."""
        self._ensure_initialized()
        
        try:
            # Clear vector store
            self._vector_store.reset()
            
            # Clear topic storage
            self._topic_storage.clear()
            
            # Clear registries
            self._save_md5_registry({})
            self._save_indexed_registry({})
            
            # Delete PDF files
            for file_path in self.CANVAS_RAG_DIR.glob("*.pdf"):
                try:
                    file_path.unlink()
                except Exception as e:
                    logger.warning(f"Could not delete {file_path}: {e}")
            
            return {
                "success": True,
                "message": "Canvas index reset successfully"
            }
        except Exception as e:
            logger.error(f"Error resetting Canvas index: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def remove_index(
        self,
        filename: str,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Remove index for a Canvas file (keep the file itself).
        
        Cleans up: ChromaDB collection, legacy vector store,
        indexed registry (JSON), topic storage, and PostgreSQL record.
        """
        self._ensure_initialized()
        
        try:
            hash_to_remove = None
            
            # Source 1: Find file hash in indexed_files_registry (per-user)
            indexed_registry = self._load_indexed_registry(user_id)
            for hash_val, data in indexed_registry.items():
                if data.get("filename") == filename:
                    hash_to_remove = hash_val
                    break
            
            # Source 2: Find file hash in collection_manager registry
            if not hash_to_remove:
                try:
                    indexed_files = self._collection_manager.get_indexed_files()
                    for file_info in indexed_files:
                        if file_info.get("filename") == filename:
                            hash_to_remove = file_info.get("file_hash")
                            break
                except Exception as e:
                    logger.warning(f"Could not search collection_manager: {e}")
            
            # Source 3: Find file hash from DB
            if not hash_to_remove and db_session and user_id:
                try:
                    rows = SyncRAGCollectionRepository.get_all_documents_with_topics(
                        db_session, _uuid.UUID(user_id),
                        source=RAGSourceType.CANVAS,
                    )
                    for r in rows:
                        if r.get("filename") == filename:
                            hash_to_remove = r.get("file_hash")
                            break
                except Exception as e:
                    logger.warning(f"Could not search DB for file hash: {e}")
            
            if not hash_to_remove:
                return {
                    "success": False,
                    "error": f"File not indexed: {filename}"
                }
            
            # Remove from per-file collection manager
            try:
                deleted = self._collection_manager.delete_collection(hash_to_remove)
                if deleted:
                    logger.info(f"Deleted collection for file hash: {hash_to_remove}")
                else:
                    logger.warning(f"Collection not found in manager for hash: {hash_to_remove}")
                # Retry cleanup of any directories that couldn't be deleted
                # due to locked file handles (e.g., SQLite).
                self._collection_manager._cleanup_orphaned_directories()
            except Exception as e:
                logger.warning(f"Could not delete from collection_manager: {e}")
            
            # Remove from legacy vector store (backwards compatibility)
            try:
                if self._vector_store:
                    self._vector_store.delete_by_filter({"file_hash": hash_to_remove})
            except Exception as e:
                logger.warning(f"Could not delete from vector store: {e}")
            
            # Remove from indexed registry (per-user)
            if hash_to_remove in indexed_registry:
                del indexed_registry[hash_to_remove]
                self._save_indexed_registry(indexed_registry, user_id)
            
            # Remove topics
            self._topic_storage.remove_document(hash_to_remove)
            
            # Remove from PostgreSQL
            if db_session and user_id:
                try:
                    SyncRAGCollectionRepository.unregister(
                        db_session,
                        file_hash=hash_to_remove,
                        user_id=_uuid.UUID(user_id),
                        source=RAGSourceType.CANVAS,
                    )
                    db_session.commit()
                except Exception as e:
                    logger.warning(f"Could not remove DB record: {e}")
                    db_session.rollback()
            
            return {
                "success": True,
                "message": f"Index removed for: {filename}"
            }
        except Exception as e:
            logger.error(f"Error removing index: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def delete_file(
        self,
        filename: str,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Delete a Canvas file and its index data (scoped to user).
        
        Cascades: first removes index (ChromaDB + DB + topics),
        then deletes physical file and MD5 registry entry.
        """
        try:
            # First, cascade remove index if file is indexed
            self.remove_index(filename, user_id=user_id, db_session=db_session)
            
            # Scope to per-user directory
            target_dir = self._get_user_dir(user_id) if user_id else self.CANVAS_RAG_DIR
            file_path = target_dir / filename
            
            # Delete physical file
            if file_path.exists():
                file_path.unlink()
            
            # Remove from MD5 registry (per-user)
            registry = self._load_md5_registry(user_id)
            hash_to_remove = None
            for hash_val, fname in registry.items():
                if fname == filename:
                    hash_to_remove = hash_val
                    break
            if hash_to_remove:
                del registry[hash_to_remove]
                self._save_md5_registry(registry, user_id)
            
            return {
                "success": True,
                "message": f"Removed local cached file: {filename}"
            }
        except Exception as e:
            logger.error(f"Error deleting Canvas file: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# Global instance getter
def get_canvas_rag_service() -> CanvasRAGService:
    return CanvasRAGService.get_instance()
