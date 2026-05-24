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
import logging
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from datetime import datetime

import httpx
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from .config import rag_config
from .ingest import load_pdf_documents, get_file_metadata
from .chunking import chunk_documents
from .lang_utils import detect_language
from .vectorstore import ChromaVectorStore
from .collection_manager import (
    PerFileCollectionManager,
    get_canvas_collection_manager,
    CollectionNameGenerator,
    CollectionRegistry,
)
from .retriever import DocumentRetriever, MultiCollectionRetriever
from .rag_chain import RAGChain
from .quiz_generator import QuizGenerator
from .llm_providers import BaseLLM, LLMFactory
from .rag_repository import (
    SyncRAGCollectionRepository,
    SyncCanvasCourseDomainDocRepository,
)
from backend.database.models.rag_document import RAGSourceType
from backend.core.logger import quiz_logger, canvas_logger
from backend.utils.file_state import locked_json_state, read_json_file

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
        self._lock = threading.RLock()
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._load()

    @staticmethod
    def _make_key(file_hash: str, user_id: Optional[str] = None) -> str:
        if user_id:
            return f"{user_id}:{file_hash}"
        return file_hash
    
    def _load(self):
        try:
            with self._lock:
                self._topics = read_json_file(self.storage_file, dict)
                logger.info(f"Loaded Canvas topics for {len(self._topics)} documents")
        except Exception as e:
            logger.warning(f"Could not load Canvas topics: {e}")
            self._topics = {}
    
    def _save(self):
        try:
            with self._lock:
                with locked_json_state(self.storage_file, dict) as state:
                    state.clear()
                    state.update(self._topics)
                    self._topics = dict(state)
        except Exception as e:
            logger.error(f"Could not save Canvas topics: {e}")
    
    def save_topics(
        self,
        file_hash: str,
        filename: str,
        topics: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ):
        key = self._make_key(file_hash, user_id)
        self._topics[key] = {
            "filename": filename,
            "topics": topics,
            "extracted_at": datetime.now().isoformat(),
            "user_id": user_id,
        }
        self._save()
    
    def get_topics(self, file_hash: str, user_id: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
        key = self._make_key(file_hash, user_id)
        if key in self._topics:
            return self._topics[key].get("topics", [])
        return None
    
    def get_topics_by_filename(
        self,
        filename: str,
        user_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, str]]]:
        logger.info(f"Looking for topics with filename: {filename}")
        logger.info(f"Available files in topics: {[d.get('filename') for h, d in self._topics.items()]}")
        for _file_hash, data in self._topics.items():
            if data.get("filename") == filename and (user_id is None or data.get("user_id") == user_id):
                topics = data.get("topics", [])
                logger.info(f"Found {len(topics)} topics for {filename}")
                return topics
        logger.info(f"No topics found for {filename}")
        return None
    
    def has_topics(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        return self._make_key(file_hash, user_id) in self._topics
    
    def get_all_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        documents = []
        for key, data in self._topics.items():
            entry_user = data.get("user_id")
            if user_id is not None and entry_user != user_id:
                continue
            file_hash = key.split(":", 1)[1] if ":" in key else key
            documents.append({
                "file_hash": file_hash,
                "filename": data.get("filename", "unknown"),
                "topic_count": len(data.get("topics", [])),
                "extracted_at": data.get("extracted_at"),
                "user_id": entry_user,
            })
        return documents
    
    def remove_document(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        key = self._make_key(file_hash, user_id)
        if key in self._topics:
            del self._topics[key]
            self._save()
            return True
        return False
    
    def update_topics_by_filename(
        self,
        filename: str,
        topics: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ) -> bool:
        for file_hash, data in self._topics.items():
            if data.get("filename") == filename and (user_id is None or data.get("user_id") == user_id):
                self._topics[file_hash]["topics"] = topics
                self._topics[file_hash]["updated_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False
    
    def clear(self, user_id: Optional[str] = None):
        if user_id is None:
            self._topics = {}
        else:
            keys_to_remove = [
                key for key, data in self._topics.items()
                if data.get("user_id") == user_id
            ]
            for key in keys_to_remove:
                del self._topics[key]
        self._save()


class CanvasRAGService:
    """
    RAG Service specifically for Canvas-sourced documents.
    
    Uses per-file ChromaDB collections to enable concurrent multi-user indexing.
    Each file gets its own collection named like 'canvas_{course_id}_{file_hash}'.
    """
    
    _instance: Optional["CanvasRAGService"] = None
    _instance_lock = threading.Lock()
    _init_lock = threading.Lock()
    
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
        self._metadata_registry: Optional[CollectionRegistry] = None
        
        self._initialized = False
    
    def _ensure_initialized(self):
        """Ensure all components are initialized (double-checked locking)."""
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._do_initialize()

    def _ensure_topic_storage(self):
        """Lightweight init: only topic storage, no embedding/ChromaDB/LLM."""
        if self._topic_storage is not None:
            return
        with self._init_lock:
            if self._topic_storage is not None:
                return
            self._topic_storage = CanvasTopicStorage(str(self.CANVAS_RAG_DIR))

    def _ensure_metadata_only(self):
        """Lightweight init: topic storage + collection registry (no embedding/LLM)."""
        self._ensure_topic_storage()
        if self._metadata_registry is not None:
            return
        with self._init_lock:
            if self._metadata_registry is not None:
                return
            self._metadata_registry = CollectionRegistry(
                str(self.CANVAS_CHROMA_DIR / "collection_registry.json")
            )

    def _ensure_collection_manager(self):
        """Medium-weight init: collection manager + topic storage (no LLM/retriever/chain).
        
        With lazy embeddings in PerFileCollectionManager, this does NOT load
        the embedding model (~500 MB) — only the registry + directory structure.
        Embeddings are loaded on-demand when get_or_create_collection() is called.
        Safe to use in the backend process for delete/reset operations.
        """
        self._ensure_topic_storage()
        if self._collection_manager is not None:
            return
        with self._init_lock:
            if self._collection_manager is not None:
                return
            self._collection_manager = get_canvas_collection_manager()
            # Also populate metadata registry from the manager's registry
            if self._metadata_registry is None:
                self._metadata_registry = self._collection_manager.registry

    def _do_initialize(self):
        """Actual initialization — must be called under _init_lock."""
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
        """Get singleton instance (double-checked locking)."""
        if cls._instance is None:
            with cls._instance_lock:
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
        try:
            return read_json_file(registry_file, dict)
        except Exception as e:
            logger.warning(f"Failed to load Canvas MD5 registry: {e}")
            return {}
    
    def _save_md5_registry(self, registry: Dict[str, str], user_id: Optional[str] = None):
        """Save MD5 registry for Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_md5_registry_file(user_id) if user_id else self.md5_registry_file
        try:
            with locked_json_state(registry_file, dict) as state:
                state.clear()
                state.update(registry)
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
        try:
            return read_json_file(registry_file, dict)
        except Exception as e:
            logger.warning(f"Failed to load indexed files registry: {e}")
            return {}
    
    def _save_indexed_registry(self, registry: Dict[str, Dict], user_id: Optional[str] = None):
        """Save registry of indexed Canvas files (per-user if user_id provided)"""
        registry_file = self._get_user_indexed_registry_file(user_id) if user_id else self.indexed_files_registry
        try:
            with locked_json_state(registry_file, dict) as state:
                state.clear()
                state.update(registry)
        except Exception as e:
            logger.error(f"Failed to save indexed files registry: {e}")

    def _indexed_registry_has(
        self,
        *,
        user_id: Optional[str],
        file_hash: str,
        course_id: Optional[int],
    ) -> bool:
        """Check whether indexed_files.json has an entry for (file_hash, course_id).

        Looks up both the new course-scoped key ``{course_id}:{file_hash}`` and
        the legacy bare-hash key (only when its stored ``course_id`` matches).
        """
        registry = self._load_indexed_registry(user_id)
        if course_id is not None:
            scoped_key = f"{course_id}:{file_hash}"
            if scoped_key in registry:
                return True
        legacy = registry.get(file_hash)
        if legacy is not None:
            if course_id is None:
                return True
            return legacy.get("course_id") == course_id
        return False
    
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

            registry_file = self._get_user_md5_registry_file(user_id) if user_id else self.md5_registry_file
            with locked_json_state(registry_file, dict) as registry:
                existing = registry.get(md5_hash)
                if existing:
                    return {
                        "success": True,
                        "status": "duplicate",
                        "md5_hash": md5_hash,
                        "existing_filename": existing,
                        "message": f"File already exists as: {existing}"
                    }

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

                registry[md5_hash] = file_path.name
            
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
        groq_api_key: Optional[str] = None,
        key_pool: Optional[Any] = None,
        force_reindex: bool = False,
    ) -> Dict[str, Any]:
        """
        Ingest a Canvas PDF document into a per-file collection.
        
        Args:
            file_path: Path to the PDF file
            extract_topics: Whether to extract topics after indexing
            course_id: Canvas course ID for collection naming
            user_id: User ID for per-user scoping
            db_session: Sync DB session for metadata persistence
            groq_api_key: Optional fresh API key for topic extraction
            key_pool: Optional ``KeyPool`` for round-robin Groq key rotation
                during the inline topic-extraction step. When provided, the
                pool is used in preference to ``groq_api_key`` and the caller
                is responsible for flushing its counters afterwards.
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

            # Pick up delete/reindex changes made by other processes before duplicate checks.
            self._collection_manager.ensure_fresh_state()

            # Force re-index path: explicitly purge any prior state for this
            # (filename, user) so a stale cross-process registry / DB row from
            # a recent delete cannot short-circuit us into ``already_indexed``.
            if force_reindex:
                logger.info(
                    "Canvas force_reindex requested: purging prior state for %s (hash=%s, user=%s, course=%s)",
                    filename, file_hash, user_id, course_id,
                )
                try:
                    self.remove_index(
                        filename,
                        user_id=user_id,
                        course_id=course_id,
                        db_session=db_session,
                    )
                except Exception as _purge_exc:
                    logger.warning(
                        "force_reindex pre-purge failed for %s: %s", filename, _purge_exc,
                    )
                # Refresh again after the purge so the duplicate checks below
                # observe a clean registry / DB.
                self._collection_manager.ensure_fresh_state()

            already_indexed = False
            collection_name = None
            topics_extracted: List[Dict[str, str]] = []
            indexed_source = None  # 'db' | 'registry' — for debug logging only

            if db_session and user_id and course_id is not None:
                try:
                    user_uuid = _uuid.UUID(user_id)
                    already_indexed = SyncRAGCollectionRepository.is_indexed_canvas(
                        db_session,
                        user_id=user_uuid,
                        course_id=int(course_id),
                        file_hash=file_hash,
                    )
                    if already_indexed:
                        indexed_source = "db"
                        collection_name = SyncRAGCollectionRepository.get_collection_name_canvas(
                            db_session,
                            user_id=user_uuid,
                            course_id=int(course_id),
                            file_hash=file_hash,
                        )
                except Exception as e:
                    logger.warning(f"Canvas DB indexed check failed: {e}")
                    db_session.rollback()

            if not already_indexed:
                registry_meta = self._collection_manager.registry.get(
                    file_hash, user_id=user_id, course_id=course_id,
                )

                # Self-heal stale legacy entries that no longer have a user-scoped
                # indexed-registry row or DB record. These can be left behind by
                # older delete flows and would otherwise block re-indexing.
                if (
                    registry_meta is not None
                    and user_id is not None
                    and registry_meta.user_id is None
                    and not self._indexed_registry_has(
                        user_id=user_id, file_hash=file_hash, course_id=course_id,
                    )
                ):
                    logger.warning(
                        "Detected stale legacy Canvas registry entry for %s; removing it before re-index",
                        filename,
                    )
                    try:
                        self._collection_manager.delete_collection(
                            file_hash, user_id=user_id, course_id=course_id,
                        )
                    except Exception as e:
                        logger.warning(f"Could not delete stale legacy Canvas registry entry: {e}")
                        try:
                            self._collection_manager.registry.unregister(
                                file_hash, user_id=user_id, course_id=course_id,
                            )
                        except Exception:
                            pass
                    self._topic_storage.remove_document(file_hash, user_id=user_id)
                    self._topic_storage.remove_document(file_hash, user_id=None)
                    registry_meta = self._collection_manager.registry.get(
                        file_hash, user_id=user_id, course_id=course_id,
                    )

                if registry_meta is not None and registry_meta.is_indexed:
                    already_indexed = True
                    indexed_source = "registry"
                    collection_name = registry_meta.collection_name

            if already_indexed:
                logger.info(
                    "Canvas document already indexed in per-file collection: %s | source=%s | hash=%s | collection=%s | user=%s",
                    file_path, indexed_source, file_hash, collection_name, user_id,
                )

                has_topics = False
                if db_session and user_id and course_id is not None:
                    try:
                        has_topics = SyncRAGCollectionRepository.has_topics_canvas(
                            db_session,
                            user_id=_uuid.UUID(user_id),
                            course_id=int(course_id),
                            file_hash=file_hash,
                        )
                    except Exception as e:
                        logger.warning(f"Canvas DB topics check failed: {e}")
                        db_session.rollback()
                if not has_topics:
                    has_topics = self._topic_storage.has_topics(file_hash, user_id=user_id)
                
                # If already indexed but no topics, extract them now
                if extract_topics and not has_topics:
                    logger.info(f"Extracting topics for already indexed document: {file_path}")
                    try:
                        topics_extracted = self._extract_and_save_topics(
                            file_hash=file_hash,
                            filename=filename,
                            course_id=course_id,
                            user_id=user_id,
                            groq_api_key=groq_api_key,
                            key_pool=key_pool,
                        )
                        has_topics = len(topics_extracted) > 0
                        if has_topics and db_session and user_id and course_id is not None:
                            try:
                                row = SyncRAGCollectionRepository.get_canvas_by_course_and_hash(
                                    db_session,
                                    user_id=_uuid.UUID(user_id),
                                    course_id=int(course_id),
                                    file_hash=file_hash,
                                )
                                if row:
                                    SyncRAGCollectionRepository.save_topics(
                                        db_session,
                                        collection_id=row.id,
                                        topics=topics_extracted,
                                    )
                                    db_session.commit()
                            except Exception as e:
                                logger.warning(f"Could not persist Canvas topics to PostgreSQL: {e}")
                                db_session.rollback()
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
            from .bench import bench_stage  # local import: keeps module-load light
            with bench_stage("pdf_load", file=filename) as _pl:
                documents = load_pdf_documents(file_path)
                _pl["pages"] = len(documents)
            
            if not documents:
                return {
                    "success": False,
                    "error": "No content extracted from PDF",
                    "chunks_added": 0
                }
            
            # Chunk documents
            with bench_stage("chunking", file=filename) as _ch:
                chunks = chunk_documents(documents)
                _ch["chunks"] = len(chunks)

            # Detect dominant language across chunks (best-effort, V1).
            try:
                detected_language = detect_language(chunks)
            except Exception as _lang_exc:
                logger.warning("Language detection failed for %s: %s", filename, _lang_exc)
                detected_language = None

            # Add to per-file Canvas collection (NOT global collection)
            # This is the key change that enables concurrent indexing
            added_count = self._collection_manager.add_documents(
                file_hash=file_hash,
                filename=filename,
                documents=chunks,
                course_id=course_id,
                replace_existing=True,  # Idempotent: re-indexing replaces old data
                user_id=user_id,
            )
            
            collection_name = self._collection_manager.get_collection_name(
                file_hash,
                course_id,
                user_id=user_id,
            )
            logger.info(f"Successfully ingested {added_count} chunks from Canvas file into collection: {collection_name}")
            
            # Extract and save topics (pass chunks directly for efficiency)
            if extract_topics and added_count > 0:
                try:
                    with bench_stage(
                        "topic_extract",
                        file=filename,
                        chunks=len(chunks),
                    ) as _tp:
                        topics_extracted = self._extract_and_save_topics(
                            file_hash=file_hash,
                            filename=filename,
                            chunks=chunks,
                            course_id=course_id,
                            user_id=user_id,
                            groq_api_key=groq_api_key,
                            key_pool=key_pool,
                        )
                        _tp["topics"] = len(topics_extracted)
                except Exception as e:
                    logger.warning(f"Failed to extract topics: {e}")
            
            # Update indexed files registry (per-user, per-course key)
            # Key format: ``{course_id}:{file_hash}`` for Canvas (course_id required
            # after migration 016). Legacy entries keyed by bare ``file_hash`` are
            # still readable but new writes always use the prefixed form.
            indexed_registry_file = self._get_user_indexed_registry_file(user_id) if user_id else self.indexed_files_registry
            registry_key = (
                f"{course_id}:{file_hash}" if course_id is not None else file_hash
            )
            with locked_json_state(indexed_registry_file, dict) as indexed_registry:
                indexed_registry[registry_key] = {
                    "file_hash": file_hash,
                    "filename": filename,
                    "file_path": file_path,
                    "collection_name": collection_name,
                    "course_id": course_id,
                    "indexed_at": datetime.now().isoformat(),
                    "chunks_added": added_count,
                    "topic_count": len(topics_extracted)
                }
            
            # ---- Persist to PostgreSQL when session available ----
            col_row = None
            if db_session and user_id:
                if course_id is None:
                    logger.warning(
                        "Canvas ingest skipped DB persist: course_id=None for file=%s hash=%s user=%s. "
                        "This indicates a caller bug — every Canvas indexing path must pass course_id "
                        "after migration 016_canvas_unique_per_course.",
                        filename, file_hash, user_id,
                    )
                else:
                    try:
                        col_row = SyncRAGCollectionRepository.register_canvas(
                            db_session,
                            user_id=_uuid.UUID(user_id),
                            course_id=int(course_id),
                            file_hash=file_hash,
                            filename=filename,
                            collection_name=collection_name or f"canvas_{file_hash[:16]}",
                            chunk_count=added_count,
                            is_indexed=True,
                            language=detected_language,
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
                "language": detected_language,
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
        course_id: Optional[int] = None,
        user_id: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        key_pool: Optional[Any] = None,
    ) -> List[Dict[str, str]]:
        """Extract topics from document and save to Canvas topic storage.
        
        Args:
            file_hash: Hash of the file
            filename: Name of the file
            num_topics: Number of topics to extract
            chunks: Pre-loaded chunks (optional, used during indexing)
            course_id: Canvas course ID for collection lookup
            groq_api_key: Optional fresh API key (from DB/settings); when
                provided a temporary LLM is used instead of the cached singleton.
            key_pool: Optional KeyPool for round-robin rotation; when provided,
                Groq rate-limit / auth errors trigger a retry with the next key.
                Each error is recorded via ``pool.mark_error`` so admins can see
                which keys are unhealthy on the admin panel.
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
                        course_id=course_id,
                        user_id=user_id,
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

            # Use a fresh LLM when a key is explicitly provided (e.g. resolved
            # from DB) so that admin-panel key changes take effect without
            # restarting the worker.
            from .llm_providers import LLMFactory as _LLMFactory

            def _build_llm(api_key: Optional[str]):
                if api_key:
                    return _LLMFactory.create(groq_api_key=api_key)
                return self._llm_provider

            def _is_rate_limit_or_auth_error(err: Exception) -> bool:
                msg = str(err).lower()
                return any(
                    sig in msg
                    for sig in (
                        "429", "rate_limit", "rate limit", "quota",
                        "401", "invalid_api_key", "invalid api key",
                        "unauthorized",
                    )
                )

            response = None
            current_key_info = None
            current_api_key = groq_api_key
            llm = _build_llm(current_api_key)

            # When the pool is available, prefer pool keys (rotates load).
            if key_pool is not None and getattr(key_pool, "size", 0) > 0:
                current_key_info = key_pool.next_key()
                if current_key_info:
                    current_api_key = current_key_info["plain_key"]
                    llm = _build_llm(current_api_key)

            # Retry up to (pool_size) times when pool is present, else 1.
            max_attempts = max(1, key_pool.size) if key_pool is not None else 1
            last_err: Optional[Exception] = None
            for attempt in range(max_attempts):
                try:
                    response_msg = llm.invoke(prompt)
                    response = response_msg.content if hasattr(response_msg, 'content') else str(response_msg)
                    if key_pool is not None and current_key_info is not None:
                        key_pool.mark_success(current_key_info["id"])
                    last_err = None
                    break
                except Exception as invoke_err:
                    last_err = invoke_err
                    is_rl = _is_rate_limit_or_auth_error(invoke_err)
                    logger.warning(
                        "Topic-extract LLM call failed (attempt %d/%d, rate_limit=%s, key=%s): %s",
                        attempt + 1, max_attempts, is_rl,
                        (current_key_info or {}).get("name", "<env>"),
                        invoke_err,
                    )
                    if key_pool is not None and current_key_info is not None:
                        key_pool.mark_error(current_key_info["id"])
                    # If not a recoverable error or no pool to rotate, bail out.
                    if not is_rl or key_pool is None:
                        break
                    next_info = key_pool.next_key()
                    if next_info is None:
                        logger.error("Topic-extract: key pool exhausted")
                        break
                    current_key_info = next_info
                    current_api_key = next_info["plain_key"]
                    llm = _build_llm(current_api_key)

            if response is None:
                # All attempts failed — re-raise so caller can mark the job /
                # surface a meaningful message instead of returning 0 topics.
                if last_err is not None:
                    raise last_err
                return []

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
                self._topic_storage.save_topics(file_hash, filename, topics, user_id=user_id)
            
            return topics
            
        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return []
    
    def extract_topics_for_file(
        self,
        filename: str,
        num_topics: int = 10,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
        groq_api_key: Optional[str] = None,
        key_pool: Optional[Any] = None,
        course_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Extract topics for a specific file by filename.

        When ``course_id`` is supplied, all lookups are scoped to that course
        so the same hash existing in multiple courses cannot be resolved
        ambiguously. Topic extraction itself is read-only / additive, so
        course_id is *recommended* but not strictly required here.
        """
        self._ensure_initialized()

        file_hash = None
        # Trust the caller-supplied course_id over the one discovered during
        # lookup; lookups still record course_id when none was provided.
        resolved_course_id = course_id

        if db_session and user_id:
            try:
                user_uuid = _uuid.UUID(user_id)
                row = None
                if course_id is not None:
                    row = SyncRAGCollectionRepository.get_by_filename_canvas(
                        db_session,
                        filename,
                        user_uuid,
                        int(course_id),
                    )
                if row is None and course_id is None:
                    row = SyncRAGCollectionRepository.get_by_filename(
                        db_session,
                        filename,
                        user_uuid,
                        source=RAGSourceType.CANVAS,
                    )
                if row:
                    file_hash = row.file_hash
                    resolved_course_id = row.course_id
            except Exception as e:
                logger.warning(f"DB lookup failed for extract_topics_for_file: {e}")
                db_session.rollback()

        if not file_hash:
            indexed_registry = self._load_indexed_registry(user_id)
            for hash_val, data in indexed_registry.items():
                if data.get("filename") != filename:
                    continue
                if course_id is not None and data.get("course_id") != int(course_id):
                    continue
                file_hash = data.get("file_hash") or hash_val
                resolved_course_id = data.get("course_id")
                break

        if not file_hash:
            matching = self._collection_manager.registry.get_by_filenames(
                [filename], user_id=user_id,
                course_id=int(course_id) if course_id is not None else None,
            )
            if matching:
                file_hash = matching[0].file_hash
                resolved_course_id = matching[0].course_id

        # Final fallback: case/whitespace/comma-insensitive match across the
        # registry. Frontend may pass the raw display_name when the /indexed
        # list filtered the canonical doc out (e.g. transient Canvas-permission
        # check failure), so an exact-string lookup will miss.
        if not file_hash:
            def _norm(name: str) -> str:
                return " ".join((name or "").lower().replace(",", "").split())

            target = _norm(filename)
            target_base = target[:-4] if target.endswith(".pdf") else target

            indexed_registry = self._load_indexed_registry(user_id)
            for hash_val, data in indexed_registry.items():
                cand = _norm(data.get("filename") or "")
                cand_base = cand[:-4] if cand.endswith(".pdf") else cand
                if cand == target or cand_base == target_base or (
                    target_base and (target_base in cand_base or cand_base in target_base)
                ):
                    if course_id is not None and data.get("course_id") != int(course_id):
                        continue
                    file_hash = data.get("file_hash") or hash_val
                    resolved_course_id = data.get("course_id")
                    break

            if not file_hash:
                try:
                    all_meta = self._collection_manager.registry.get_all(user_id=user_id)
                    for meta in all_meta:
                        cand = _norm(meta.filename or "")
                        cand_base = cand[:-4] if cand.endswith(".pdf") else cand
                        if cand == target or cand_base == target_base or (
                            target_base and (target_base in cand_base or cand_base in target_base)
                        ):
                            if course_id is not None and meta.course_id != int(course_id):
                                continue
                            file_hash = meta.file_hash
                            resolved_course_id = meta.course_id
                            break
                except Exception:
                    pass

        if not file_hash:
            return {
                "success": False,
                "error": f"File not indexed: {filename}"
            }
        
        try:
            topics = self._extract_and_save_topics(
                file_hash,
                filename,
                num_topics,
                course_id=resolved_course_id,
                user_id=user_id,
                groq_api_key=groq_api_key,
                key_pool=key_pool,
            )
            if topics and db_session and user_id:
                try:
                    row = None
                    if resolved_course_id is not None:
                        row = SyncRAGCollectionRepository.get_canvas_by_course_and_hash(
                            db_session,
                            user_id=_uuid.UUID(user_id),
                            course_id=int(resolved_course_id),
                            file_hash=file_hash,
                        )
                    if row is None and resolved_course_id is not None:
                        # File was indexed via legacy JSON registry but never
                        # got a DB row. Auto-register so future queries (and
                        # the UI's topic_count) see it.
                        try:
                            collection_name = (
                                self._collection_manager.get_collection_name(
                                    file_hash, course_id=resolved_course_id, user_id=user_id,
                                )
                                if self._collection_manager else f"canvas_{file_hash[:12]}"
                            )
                        except Exception:
                            collection_name = f"canvas_{file_hash[:12]}"
                        try:
                            row = SyncRAGCollectionRepository.register_canvas(
                                db_session,
                                user_id=_uuid.UUID(user_id),
                                course_id=int(resolved_course_id),
                                file_hash=file_hash,
                                filename=filename,
                                collection_name=collection_name,
                                chunk_count=0,
                                is_indexed=True,
                            )
                        except Exception as reg_err:
                            logger.warning(
                                "Could not auto-register DB row for legacy file_hash=%s: %s",
                                file_hash, reg_err,
                            )
                            row = None
                    if row is None and resolved_course_id is None:
                        logger.warning(
                            "extract_topics_for_file: course_id unknown for file=%s hash=%s user=%s; "
                            "skipping DB topic persistence (V2 requires course_id).",
                            filename, file_hash, user_id,
                        )
                    if row:
                        SyncRAGCollectionRepository.save_topics(
                            db_session,
                            collection_id=row.id,
                            topics=topics,
                        )
                        db_session.commit()
                except Exception as e:
                    logger.warning(f"Could not persist extracted Canvas topics: {e}")
                    db_session.rollback()
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
        """Get topics for a Canvas document (lightweight — no embedding/LLM init)."""
        self._ensure_topic_storage()
        
        topics = None
        if db_session and user_id:
            try:
                topics = SyncRAGCollectionRepository.get_topics_by_filename(
                    db_session,
                    filename,
                    _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
            except Exception as e:
                logger.warning(f"DB query failed for get_document_topics, falling back to legacy: {e}")
                db_session.rollback()
        if topics is None:
            raw = self._topic_storage.get_topics_by_filename(filename, user_id=user_id)
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
        """Update topics for a Canvas document (lightweight — no embedding/LLM init)."""
        self._ensure_topic_storage()
        
        topic_dicts = [{"name": t, "description": ""} for t in topics]
        
        success = False
        if db_session and user_id:
            try:
                success = SyncRAGCollectionRepository.update_topics_by_filename(
                    db_session,
                    filename,
                    topic_dicts,
                    _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
                if success:
                    db_session.commit()
            except Exception as e:
                logger.warning(f"DB query failed for update_document_topics, falling back to legacy: {e}")
                db_session.rollback()
        if not success:
            success = self._topic_storage.update_topics_by_filename(filename, topic_dicts, user_id=user_id)
        
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
        """List all indexed Canvas documents (lightweight — no embedding/LLM init)."""
        self._ensure_metadata_only()
        registry = self._collection_manager.registry if self._collection_manager else self._metadata_registry
        
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
                    topic_count = r.get("topic_count", 0)
                    # Fallback: if DB has no topic row yet (legacy doc, or a
                    # previous extract failed to persist to RAGDocumentTopic
                    # because file_hash mismatched), use JSON topic storage so
                    # the UI still shows the actual count.
                    if topic_count == 0:
                        try:
                            json_topics = self._topic_storage.get_topics(
                                r["file_hash"], user_id=user_id,
                            ) or []
                            if json_topics:
                                topic_count = len(json_topics)
                        except Exception:
                            pass
                    db_documents.append({
                        "filename": r["filename"],
                        "original_filename": r["filename"],
                        "file_hash": r["file_hash"],
                        "indexed_at": r.get("indexed_at"),
                        "chunks_added": r.get("chunk_count", 0),
                        "topic_count": topic_count,
                        "course_id": r.get("course_id"),
                    })
                    db_seen_hashes.add((r["file_hash"], r.get("course_id")))
            except Exception as e:
                logger.warning(f"DB query failed for list_indexed_documents, falling back to legacy: {e}")
                db_session.rollback()
        
        documents = list(db_documents)
        seen_hashes = set(db_seen_hashes)
        
        # Source 1: Get from indexed_files_registry (per-user)
        indexed_registry = self._load_indexed_registry(user_id)
        for hash_key, data in indexed_registry.items():
            real_file_hash = data.get("file_hash") or hash_key
            entry_course_id = data.get("course_id")
            dedup_key = (real_file_hash, entry_course_id)
            if dedup_key in seen_hashes:
                continue
            filename = data.get("filename", "unknown")
            topics = self._topic_storage.get_topics(real_file_hash, user_id=user_id) or []
            documents.append({
                "filename": filename,
                "original_filename": filename,
                "file_hash": real_file_hash,
                "indexed_at": data.get("indexed_at"),
                "chunks_added": data.get("chunks_added", 0),
                "topic_count": len(topics),
                "course_id": entry_course_id
            })
            seen_hashes.add(dedup_key)
        
        # Source 2: Get from collection_manager (per-file collections)
        # This catches files indexed via collection_manager but not in indexed_registry
        try:
            indexed_files = registry.get_all(user_id=user_id)
            for meta in indexed_files:
                file_hash = meta.file_hash
                dedup_key = (file_hash, meta.course_id)
                if file_hash and dedup_key not in seen_hashes:
                    filename = meta.filename or "unknown"
                    topics = self._topic_storage.get_topics(file_hash, user_id=user_id) or []
                    documents.append({
                        "filename": filename,
                        "original_filename": filename,
                        "file_hash": file_hash,
                        "indexed_at": meta.created_at,
                        "chunks_added": meta.chunk_count,
                        "topic_count": len(topics),
                        "course_id": meta.course_id
                    })
                    seen_hashes.add(dedup_key)
        except Exception as e:
            logger.warning(f"Could not get files from collection_manager: {e}")
        
        return {
            "success": True,
            "documents": documents,
            "count": len(documents)
        }
    
    def list_downloaded_files(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """List downloaded Canvas files for a specific user (lightweight — no embedding/LLM init)."""
        self._ensure_metadata_only()
        
        try:
            files = []
            indexed_registry = self._load_indexed_registry(user_id)
            
            # Also get indexed files from collection_manager (if already initialized)
            collection_indexed_files = set()
            try:
                cm = self._collection_manager
                if cm is not None:
                    for file_info in cm.get_indexed_files(user_id=user_id):
                        collection_indexed_files.add(file_info.get("filename", ""))
                else:
                    # Use lightweight registry instead
                    for meta in self._metadata_registry.get_all(user_id=user_id):
                        collection_indexed_files.add(meta.original_filename or "")
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
    
    def get_index_stats(
        self,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Get Canvas index statistics for a specific user (lightweight — no embedding/LLM init)."""
        self._ensure_metadata_only()
        registry = self._collection_manager.registry if self._collection_manager else self._metadata_registry
        
        try:
            if db_session and user_id:
                rows = SyncRAGCollectionRepository.get_all(
                    db_session,
                    _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
                return {
                    "total_documents": len(rows),
                    "total_chunks": sum(row.chunk_count or 0 for row in rows),
                    "collection_name": "per-file-canvas-collections",
                    "unique_files": len(rows),
                }

            indexed_files = registry.get_all(user_id=user_id)
            return {
                "total_documents": len(indexed_files),
                "total_chunks": sum(meta.chunk_count or 0 for meta in indexed_files),
                "collection_name": "per-file-canvas-collections",
                "unique_files": len(indexed_files)
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
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Query the Canvas document knowledge base."""
        retrieval = self.retrieve_documents_for_query(
            question=question,
            k=k,
            selected_documents=selected_documents,
            user_id=user_id,
            db_session=db_session,
        )
        if not retrieval.get("success"):
            return {
                "success": False,
                "answer": retrieval.get(
                    "answer",
                    f"Lỗi khi xử lý câu hỏi: {retrieval.get('error', 'Unknown error')}",
                ),
                "sources": [],
                "error": retrieval.get("error", "Query failed"),
            }

        result = self._rag_chain.query_from_documents(
            question=question,
            documents=retrieval["documents"],
            return_context=return_context,
        )
        result["success"] = True
        result["collections_queried"] = retrieval.get("collections_queried", 0)
        return result
    
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
        groq_api_key: Optional[str] = None,
        *,
        course_id: Optional[int] = None,
        include_course_domain: bool = False,
        domain_quota_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Generate quiz from Canvas documents."""
        retrieval = self.retrieve_documents_for_quiz(
            topics=topics,
            num_questions=num_questions,
            selected_documents=selected_documents,
            user_id=user_id,
            db_session=db_session,
            course_id=course_id,
            include_course_domain=include_course_domain,
            domain_quota_ratio=domain_quota_ratio,
            groq_api_key=groq_api_key,
        )
        if not retrieval.get("success"):
            return {
                "success": retrieval.get("success", False),
                "questions": retrieval.get("questions", []),
                "error": retrieval.get("error") or retrieval.get("message", "Quiz retrieval failed"),
                "message": retrieval.get("message"),
            }

        try:
            # Use a local QuizGenerator if a custom API key was provided,
            # avoiding shared singleton mutation (thread-safety fix).
            quiz_gen = self._quiz_generator
            if groq_api_key:
                from .llm_providers import LLMFactory as _LLMFactory
                quiz_gen = QuizGenerator(
                    retriever=self._multi_retriever,
                    llm_provider=_LLMFactory.create(groq_api_key=groq_api_key),
                )

            result = quiz_gen.generate_quiz_from_documents(
                topic=retrieval["topic"],
                topics=retrieval["topics"],
                raw_documents=retrieval["documents"],
                num_questions=num_questions,
                difficulty=difficulty,
                language=language,
            )
            result["_resolved_hashes"] = retrieval.get("_resolved_hashes", "all")
            return result
            
        except Exception as e:
            logger.error(f"Error generating Canvas quiz: {e}")
            return {
                "success": False,
                "questions": [],
                "error": f"Lỗi khi tạo quiz: {str(e)}"
            }

    def _resolve_query_target_hashes(
        self,
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Optional[List[str]]:
        """Resolve authoritative Canvas file hashes for retrieval."""
        self._ensure_initialized()
        self._collection_manager.ensure_fresh_state()

        target_hashes = None
        if selected_documents:
            target_hashes = []
            if db_session and user_id:
                try:
                    rows = SyncRAGCollectionRepository.get_by_filenames(
                        db_session,
                        selected_documents,
                        _uuid.UUID(user_id),
                        source=RAGSourceType.CANVAS,
                    )
                    target_hashes = [row.file_hash for row in rows]
                except Exception as e:
                    logger.warning(f"Canvas DB get_by_filenames failed during query: {e}")
                    db_session.rollback()
            if not target_hashes:
                matching = self._collection_manager.registry.get_by_filenames(selected_documents, user_id=user_id)
                target_hashes = [row.file_hash for row in matching]
        elif db_session and user_id:
            try:
                rows = SyncRAGCollectionRepository.get_all(
                    db_session,
                    _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
                target_hashes = [row.file_hash for row in rows]
            except Exception as e:
                logger.warning(f"Canvas DB get_all failed during query: {e}")
                db_session.rollback()
        return target_hashes

    def retrieve_documents_for_query(
        self,
        question: str,
        k: int = 6,
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Retrieve Canvas query documents without executing the LLM step locally."""
        target_hashes = self._resolve_query_target_hashes(
            selected_documents=selected_documents,
            user_id=user_id,
            db_session=db_session,
        )
        documents = self._multi_retriever.retrieve(
            question,
            k=k,
            target_file_hashes=target_hashes,
            user_id=user_id,
        )
        return {
            "success": True,
            "documents": documents,
            "collections_queried": len(target_hashes) if target_hashes is not None else 0,
        }

    def _resolve_quiz_targets(
        self,
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
        *,
        course_id: Optional[int] = None,
        include_course_domain: bool = False,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Resolve selected Canvas docs into lecture and (optional) domain targets.

        Returns
        -------
        ``(lecture_targets, domain_targets)`` where each target is a dict with
        keys ``file_hash``, ``collection_name``, ``language`` (Optional[str]),
        and ``role`` ("lecture" | "domain").

        Behavior
        --------
        * Lecture targets come from ``selected_documents`` (preferred) or the
          full per-user Canvas index. This preserves the existing flow.
        * If ``include_course_domain`` is True, an extra bucket of domain
          targets is added — one per file marked as course domain knowledge
          for the lecture's Canvas course. Domain targets reuse the
          deterministic per-file collection name and do NOT require the
          requesting user to have a row in ``rag_collections`` for that file.
        * If a selected file is itself marked as a domain doc for the same
          course, it is **coerced** into the domain bucket (with a log) so
          the SOURCE ROLES policy still applies correctly.
        * If lecture files span multiple Canvas courses, domain injection
          is skipped (logged) — V1 only handles a single-course quiz.
        """
        lecture_targets: List[Dict[str, Any]] = []
        domain_targets: List[Dict[str, Any]] = []
        lecture_hashes_seen: set = set()

        # ── 1. Resolve lecture rows (course-scoped for Canvas) ─────────
        # course_id is REQUIRED for Canvas quiz retrieval. The same
        # filename / file_hash can exist under multiple Canvas courses for
        # the same user; a course-agnostic lookup will pull cross-course
        # rows that poison hash_to_collection_name and cause Chroma to fall
        # back to a generated name with course_id=None → 0 hits. See
        # migration 016_canvas_unique_per_course for the underlying schema.
        if course_id is None:
            raise ValueError(
                "course_id is required for Canvas quiz generation"
            )

        rows: List[Any] = []
        if selected_documents:
            if db_session and user_id:
                try:
                    rows = SyncRAGCollectionRepository.get_by_filenames_canvas(
                        db_session,
                        user_id=_uuid.UUID(user_id),
                        course_id=course_id,
                        filenames=selected_documents,
                    )
                    quiz_logger.info(
                        "Canvas DB get_by_filenames_canvas rows=%d course_id=%s files=%s",
                        len(rows), course_id,
                        [(r.filename, r.file_hash[:8]) for r in rows],
                    )
                except Exception as e:
                    logger.warning(f"Canvas DB get_by_filenames_canvas failed: {e}")
                    quiz_logger.warning(
                        f"Canvas DB get_by_filenames_canvas failed: {e}"
                    )
                    db_session.rollback()
                    rows = []
            if not rows:
                matching = self._collection_manager.registry.get_by_filenames(
                    selected_documents,
                    user_id=user_id,
                    course_id=course_id,
                )
                # Adapt registry meta -> attribute-equivalent objects
                rows = matching
                quiz_logger.info(
                    f"Canvas registry fallback course_id={course_id}: matched "
                    f"{len(matching)} of {len(selected_documents)} docs"
                )
        elif db_session and user_id:
            try:
                rows = SyncRAGCollectionRepository.get_all(
                    db_session, _uuid.UUID(user_id),
                    source=RAGSourceType.CANVAS,
                )
                # All-files fallback: filter to current course.
                rows = [r for r in rows if getattr(r, "course_id", None) == course_id]
            except Exception as e:
                logger.warning(f"Canvas DB get_all failed for quiz generation: {e}")
                quiz_logger.warning(f"Canvas DB get_all failed for quiz generation: {e}")
                db_session.rollback()
                rows = []
        else:
            quiz_logger.warning(
                f"canvas selected_documents is None/empty ({selected_documents!r}) "
                "— will query all course-scoped collections!"
            )

        # ── 2. Course is fixed by caller; no derivation from rows. ────
        # (Previously: derived single_course_id from set of rows' course_ids,
        # which collapsed to None when the same filename existed in multiple
        # courses — root cause of the cross-course quiz retrieval bug.)
        single_course_id: Optional[int] = course_id

        # ── 3. Pre-compute domain marks for that course (if any) ──────
        domain_hashes_for_course: set = set()
        if (
            include_course_domain
            and single_course_id is not None
            and db_session is not None
        ):
            try:
                domain_hashes_for_course = set(
                    SyncCanvasCourseDomainDocRepository.get_enabled_hashes(
                        db_session, single_course_id,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to fetch domain marks for course={single_course_id}: {e}")
                quiz_logger.warning(f"domain_marks_fetch_failed course_id={single_course_id} err={e}")
                if db_session is not None:
                    db_session.rollback()
                domain_hashes_for_course = set()

        # ── 4. Build lecture targets, coercing domain-marked selections ──
        coerced_to_domain: List[Dict[str, Any]] = []
        for r in rows:
            file_hash = getattr(r, "file_hash", None)
            if not file_hash:
                continue
            collection_name = getattr(r, "collection_name", None)
            # Canvas safety net: never let a target carry a None
            # collection_name — that would force query_collection() to fall
            # back to a generated name with course_id=None.
            if not collection_name:
                collection_name = CollectionNameGenerator.for_canvas_file(
                    file_hash, single_course_id,
                )
                quiz_logger.warning(
                    "QUIZ_RESOLVE_DOC_REPAIRED filename=%s hash=%s course_id=%s "
                    "collection_name=%s (row missing collection_name)",
                    getattr(r, "filename", "?"), file_hash[:8],
                    single_course_id, collection_name,
                )
            language = getattr(r, "language", None)
            quiz_logger.info(
                "QUIZ_RESOLVE_DOC filename=%s hash=%s course_id=%s collection_name=%s",
                getattr(r, "filename", "?"), file_hash[:8],
                single_course_id, collection_name,
            )
            target = {
                "file_hash": file_hash,
                "collection_name": collection_name,
                "language": language,
                "role": "lecture",
            }
            if file_hash in domain_hashes_for_course:
                target["role"] = "domain"
                coerced_to_domain.append(target)
                quiz_logger.info(
                    "quiz_lecture_selection_coerced_to_domain "
                    f"file_hash={file_hash[:8]} course_id={single_course_id}"
                )
                continue
            if file_hash in lecture_hashes_seen:
                continue
            lecture_hashes_seen.add(file_hash)
            lecture_targets.append(target)

        # ── 5. Inject domain targets (excluding any already in lectures) ──
        if (
            include_course_domain
            and single_course_id is not None
            and db_session is not None
            and domain_hashes_for_course
        ):
            extra_hashes = [
                h for h in domain_hashes_for_course
                if h not in lecture_hashes_seen
            ]
            language_map: Dict[str, str] = {}
            try:
                language_map = SyncRAGCollectionRepository.get_language_by_hashes(
                    db_session, extra_hashes,
                )
            except Exception as e:
                logger.warning(f"Failed to bulk-fetch languages for domain hashes: {e}")
                if db_session is not None:
                    db_session.rollback()
            seen_domain: set = {t["file_hash"] for t in coerced_to_domain}
            for fh in extra_hashes:
                if fh in seen_domain:
                    continue
                seen_domain.add(fh)
                collection_name = CollectionNameGenerator.for_canvas_file(
                    fh, single_course_id,
                )
                domain_targets.append({
                    "file_hash": fh,
                    "collection_name": collection_name,
                    "language": language_map.get(fh),
                    "role": "domain",
                })
            domain_targets.extend(coerced_to_domain)

        elif coerced_to_domain:
            # Domain injection feature is on but no extra unmarked domain
            # files; still keep coerced ones so SOURCE ROLES applies.
            domain_targets.extend(coerced_to_domain)

        return lecture_targets, domain_targets

    def retrieve_documents_for_quiz(
        self,
        topics: List[str],
        num_questions: int = 5,
        selected_documents: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        db_session: Optional[Session] = None,
        *,
        course_id: Optional[int] = None,
        include_course_domain: bool = False,
        domain_quota_ratio: Optional[float] = None,
        groq_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve Canvas quiz documents without executing the LLM step locally."""
        self._ensure_initialized()
        self._collection_manager.ensure_fresh_state()

        if not topics or len(topics) == 0:
            return {
                "success": False,
                "questions": [],
                "error": "Cần có ít nhất một chủ đề để tạo quiz"
            }

        # Canvas retrieval MUST be course-scoped. Fail fast so the caller
        # (route → Celery task) bubbles the error back to the user instead
        # of silently retrieving from the wrong course.
        if course_id is None:
            quiz_logger.error(
                "QUIZ_CANVAS_NO_COURSE selected_documents=%s user_id=%s",
                selected_documents, user_id,
            )
            return {
                "success": False,
                "questions": [],
                "error": "course_id is required for Canvas quiz generation",
            }

        logger.info(f"Generating Canvas quiz: topics={topics}, num_questions={num_questions}")
        quiz_logger.info(
            "QUIZ_CANVAS_COURSE course_id=%s selected_documents=%s user_id=%s "
            "db_session=%s include_course_domain=%s domain_quota_ratio=%s",
            course_id, selected_documents, user_id,
            "present" if db_session else "None",
            include_course_domain, domain_quota_ratio,
        )

        # Feature flag gates domain injection completely.
        from backend.core.config import settings as _settings
        feature_on = bool(getattr(_settings, "ENABLE_COURSE_DOMAIN_DOCS", False))
        effective_include_domain = bool(include_course_domain) and feature_on
        try:
            lecture_targets, domain_targets = self._resolve_quiz_targets(
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=db_session,
                course_id=course_id,
                include_course_domain=effective_include_domain,
            )
        except Exception as exc:
            logger.warning(
                "quiz target resolution with domain failed (%s); "
                "falling back to lecture-only", exc,
            )
            quiz_logger.warning(
                f"quiz_targets_resolve_error err={exc} -- falling back to lecture-only"
            )
            lecture_targets, domain_targets = self._resolve_quiz_targets(
                selected_documents=selected_documents,
                user_id=user_id,
                db_session=db_session,
                course_id=course_id,
                include_course_domain=False,
            )

        # Backward-compatible flat lists for prepare_quiz_documents.
        all_targets = lecture_targets + domain_targets
        target_hashes = [t["file_hash"] for t in all_targets] if all_targets else None
        hash_to_collection = {
            t["file_hash"]: t["collection_name"]
            for t in all_targets
            if t.get("collection_name")
        }
        hash_to_course_id = {
            t["file_hash"]: int(t["course_id"])
            for t in all_targets
            if t.get("course_id") is not None
        }
        roles_by_hash = {t["file_hash"]: t["role"] for t in all_targets}
        language_by_hash = {
            t["file_hash"]: t["language"]
            for t in all_targets
            if t.get("language")
        }

        # Resolve effective domain ratio (clamped at retriever).
        effective_ratio: Optional[float] = None
        if effective_include_domain and domain_targets:
            if domain_quota_ratio is None:
                effective_ratio = float(
                    getattr(_settings, "DEFAULT_DOMAIN_QUOTA_RATIO", 0.3)
                )
            else:
                effective_ratio = float(domain_quota_ratio)

        quiz_logger.info(
            "quiz_targets course_lecture=%d domain=%d include_domain=%s ratio=%s "
            "lecture_hashes=%s domain_hashes=%s",
            len(lecture_targets),
            len(domain_targets),
            effective_include_domain,
            effective_ratio,
            [t["file_hash"][:8] for t in lecture_targets[:8]],
            [t["file_hash"][:8] for t in domain_targets[:8]],
        )

        prepared = self._quiz_generator.prepare_quiz_documents(
            topics=topics,
            num_questions=num_questions,
            target_file_hashes=target_hashes,
            user_id=user_id,
            hash_to_collection_name=hash_to_collection or None,
            roles_by_hash=roles_by_hash if roles_by_hash else None,
            language_by_hash=language_by_hash if language_by_hash else None,
            domain_quota_ratio=effective_ratio,
            groq_api_key=groq_api_key,
            course_id=int(course_id) if course_id is not None else None,
            hash_to_course_id=hash_to_course_id or None,
        )
        if not prepared.get("success"):
            return prepared

        return {
            "success": True,
            "topic": prepared["topic"],
            "topics": prepared["topics"],
            "documents": prepared["raw_documents"],
            "_resolved_hashes": len(target_hashes) if target_hashes is not None else "all",
            "_lecture_count": len(lecture_targets),
            "_domain_count": len(domain_targets),
        }
    
    def reset_index(self) -> Dict[str, Any]:
        """Reset Canvas index and clear all data."""
        self._ensure_collection_manager()
        
        try:
            self._collection_manager.reset_all()
            if self._vector_store:
                self._vector_store.reset()
            
            # Clear topic storage
            self._topic_storage.clear()
            
            # Clear registries
            self._save_md5_registry({})
            self._save_indexed_registry({})
            
            # Delete PDF files and per-user registry directories
            for file_path in self.CANVAS_RAG_DIR.rglob("*"):
                try:
                    if file_path.is_file() and (
                        file_path.suffix.lower() == ".pdf"
                        or file_path.name in {
                            ".md5_registry.json",
                            ".indexed_files.json",
                            "canvas_document_topics.json",
                        }
                    ):
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
        course_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Remove index for a Canvas file (keep the file itself).
        
        Cleans up: ChromaDB collection, legacy vector store,
        indexed registry (JSON), topic storage, PostgreSQL record,
        and any matching CanvasCourseDomainDoc marks.

        ``course_id`` is REQUIRED. See migration 016_canvas_unique_per_course
        — the same file_hash can legitimately exist under multiple Canvas
        courses for the same user, so destructive ops MUST be course-scoped
        to avoid wiping out a sibling course's index.
        """
        self._ensure_collection_manager()

        if course_id is None:
            logger.error(
                "Canvas remove_index rejected: course_id is required (filename=%s user=%s)",
                filename, user_id,
            )
            return {
                "success": False,
                "error": "course_id is required for Canvas remove_index",
            }

        logger.info(
            "Canvas remove_index start: filename=%s user=%s course=%s",
            filename, user_id, course_id,
        )
        # Pull in any registry/DB writes made by another process (typically the
        # rag worker that just finished indexing this file). Without this, the
        # FastAPI backend can hold a stale view and fail to find the entry it
        # is trying to delete — producing "Cannot delete collection: file_hash
        # ... not found in registry" warnings and orphan Chroma directories.
        try:
            self._collection_manager.ensure_fresh_state()
        except Exception as _refresh_exc:
            logger.warning(
                "remove_index: registry refresh failed (continuing): %s", _refresh_exc,
            )
        try:
            hash_to_remove = None
            # course_id is required and validated above — store as int for downstream use.
            course_id_for_domain: Optional[int] = int(course_id)
            
            # Source 1: Find file hash in indexed_files_registry (per-user), course-scoped
            indexed_registry = self._load_indexed_registry(user_id)
            for hash_val, data in indexed_registry.items():
                if (
                    data.get("filename") == filename
                    and data.get("course_id") == course_id_for_domain
                ):
                    hash_to_remove = data.get("file_hash") or hash_val
                    break
            
            # Source 2: Find file hash in collection_manager registry (course-scoped)
            if not hash_to_remove:
                try:
                    registry_matches = self._collection_manager.registry.get_by_filenames(
                        [filename],
                        user_id=user_id,
                        course_id=course_id_for_domain,
                    )
                    for meta in registry_matches:
                        if meta.filename == filename and meta.course_id == course_id_for_domain:
                            hash_to_remove = meta.file_hash
                            break
                except Exception as e:
                    logger.warning(f"Could not search collection_manager: {e}")
            
            # Source 3: Find file hash from DB (course-scoped)
            if not hash_to_remove and db_session and user_id:
                try:
                    row = SyncRAGCollectionRepository.get_by_filename_canvas(
                        db_session,
                        user_id=_uuid.UUID(user_id),
                        course_id=course_id_for_domain,
                        filename=filename,
                    )
                    if row:
                        hash_to_remove = row.file_hash
                except Exception as e:
                    logger.warning(f"Could not search DB for file hash: {e}")

            # Source 4 (fuzzy fallback): the UI sometimes hands us the raw
            # Canvas display_name (e.g. ``1 - Gioi thieu.pdf``) while the
            # local copy was suffix-renamed at download time to avoid name
            # collisions (``1 - Gioi thieu_1.pdf``). Mirror the normalization
            # used by the topic-extract resolver above so the strict lookups
            # don't silently no-op.
            if not hash_to_remove:
                def _norm(name: str) -> str:
                    return " ".join((name or "").lower().replace(",", "").split())

                target = _norm(filename)
                target_base = target[:-4] if target.endswith(".pdf") else target

                def _matches(candidate: str) -> bool:
                    cand = _norm(candidate)
                    cand_base = cand[:-4] if cand.endswith(".pdf") else cand
                    if not target_base:
                        return False
                    if cand == target or cand_base == target_base:
                        return True
                    # ``foo`` should match ``foo_1`` / ``foo_2`` (download-time
                    # collision suffix) but not ``foobar``.
                    if cand_base.startswith(target_base + "_") or target_base.startswith(cand_base + "_"):
                        return True
                    return False

                for hash_val, data in indexed_registry.items():
                    if (
                        _matches(data.get("filename") or "")
                        and data.get("course_id") == course_id_for_domain
                    ):
                        hash_to_remove = data.get("file_hash") or hash_val
                        break

                if not hash_to_remove:
                    try:
                        all_meta = self._collection_manager.registry.get_all(user_id=user_id)
                        for meta in all_meta:
                            if (
                                _matches(meta.filename or "")
                                and meta.course_id == course_id_for_domain
                            ):
                                hash_to_remove = meta.file_hash
                                break
                    except Exception as e:
                        logger.warning(f"Fuzzy registry scan failed: {e}")

                if hash_to_remove:
                    logger.info(
                        "Canvas remove_index fuzzy-matched %r -> hash=%s",
                        filename, hash_to_remove,
                    )

            if not hash_to_remove:
                logger.info(
                    "Canvas remove_index: no prior state found for %s (user=%s) \u2014 nothing to do",
                    filename, user_id,
                )
                return {
                    "success": False,
                    "error": f"File not indexed: {filename}"
                }

            logger.info(
                "Canvas remove_index resolved hash=%s course_id=%s for %s",
                hash_to_remove, course_id_for_domain, filename,
            )
            
            # Remove from per-file collection manager
            try:
                deleted = self._collection_manager.delete_collection(
                    hash_to_remove,
                    user_id=user_id,
                    course_id=course_id_for_domain,
                )
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
            
            # Remove from indexed registry (per-user) — pop course-scoped key
            # AND the legacy bare-hash key (if any) so a stale legacy entry
            # doesn't survive the delete.
            indexed_registry_file = self._get_user_indexed_registry_file(user_id) if user_id else self.indexed_files_registry
            course_scoped_key = f"{course_id_for_domain}:{hash_to_remove}"
            with locked_json_state(indexed_registry_file, dict) as registry_state:
                registry_state.pop(course_scoped_key, None)
                legacy_entry = registry_state.get(hash_to_remove)
                if legacy_entry is not None and legacy_entry.get("course_id") == course_id_for_domain:
                    registry_state.pop(hash_to_remove, None)
            
            # Remove topics
            self._topic_storage.remove_document(hash_to_remove, user_id=user_id)
            
            # Remove from PostgreSQL (course-scoped only; never legacy multi-row)
            if db_session and user_id:
                try:
                    SyncRAGCollectionRepository.unregister_canvas(
                        db_session,
                        user_id=_uuid.UUID(user_id),
                        course_id=int(course_id_for_domain),
                        file_hash=hash_to_remove,
                    )
                    db_session.commit()
                except Exception as e:
                    logger.warning(f"Could not remove DB record: {e}")
                    db_session.rollback()

            # Soft-disable any matching CanvasCourseDomainDoc marks so the file
            # cannot resurface as "course-shared domain knowledge" pointing at
            # a now-deleted RAGCollection. We only know the course_id when it
            # was captured above; if missing, skip silently.
            if db_session and course_id_for_domain is not None:
                try:
                    disabled = SyncCanvasCourseDomainDocRepository.disable(
                        db_session,
                        course_id=int(course_id_for_domain),
                        file_hash=hash_to_remove,
                    )
                    if disabled:
                        db_session.commit()
                        logger.info(
                            "Canvas remove_index: disabled CanvasCourseDomainDoc for course=%s hash=%s",
                            course_id_for_domain, hash_to_remove,
                        )
                except Exception as e:
                    logger.warning(
                        "Could not disable CanvasCourseDomainDoc for course=%s hash=%s: %s",
                        course_id_for_domain, hash_to_remove, e,
                    )
                    try:
                        db_session.rollback()
                    except Exception:
                        pass

            logger.info(
                "Canvas remove_index done: filename=%s hash=%s user=%s",
                filename, hash_to_remove, user_id,
            )
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
        course_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Delete a Canvas file and its index data (scoped to user + course).
        
        Cascades: first removes index (ChromaDB + DB + topics),
        then deletes physical file and MD5 registry entry.

        ``course_id`` is REQUIRED — see :meth:`remove_index` rationale.
        """
        if course_id is None:
            logger.error(
                "Canvas delete_file rejected: course_id is required (filename=%s user=%s)",
                filename, user_id,
            )
            return {
                "success": False,
                "error": "course_id is required for Canvas delete_file",
            }
        try:
            # First, cascade remove index if file is indexed
            self.remove_index(
                filename,
                user_id=user_id,
                db_session=db_session,
                course_id=course_id,
            )
            
            # Scope to per-user directory
            target_dir = self._get_user_dir(user_id) if user_id else self.CANVAS_RAG_DIR
            file_path = target_dir / filename
            
            # Delete physical file
            if file_path.exists():
                file_path.unlink()
            
            # Remove from MD5 registry (per-user)
            hash_to_remove = None
            registry_file = self._get_user_md5_registry_file(user_id) if user_id else self.md5_registry_file
            with locked_json_state(registry_file, dict) as registry:
                for hash_val, fname in registry.items():
                    if fname == filename:
                        hash_to_remove = hash_val
                        break
                if hash_to_remove:
                    del registry[hash_to_remove]
            
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
