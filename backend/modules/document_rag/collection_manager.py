"""
Collection Manager Module
=========================
Manages per-file/per-document ChromaDB collections to enable concurrent 
indexing without global write locks.

Key Design Principles:
- Each uploaded document gets its own collection, keyed by file_hash
- Collection names are deterministic and reproducible
- No global collection - eliminates multi-user blocking
- Thread-safe collection access with per-file granular locking

Collection Naming Strategy:
- Regular uploads: "doc_{file_hash[:16]}"
- Canvas uploads: "canvas_{course_id}_{file_hash[:16]}"
"""

import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional, List, Any, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

from .config import rag_config

logger = logging.getLogger(__name__)


@dataclass
class CollectionMetadata:
    """Metadata for a document collection."""
    collection_name: str
    file_hash: str
    filename: str
    course_id: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    chunk_count: int = 0
    is_indexed: bool = False
    user_id: Optional[str] = None  # Owner user ID for per-user isolation


class CollectionNameGenerator:
    """
    Generates deterministic, reproducible collection names.
    
    Naming conventions:
    - Regular uploads: "doc_{file_hash_prefix}"
    - Canvas files: "canvas_{course_id}_{file_hash_prefix}"
    
    ChromaDB collection name constraints:
    - 3-63 characters
    - Must start and end with alphanumeric
    - Can contain alphanumeric, underscores, hyphens
    - No consecutive periods
    """
    
    # ChromaDB name constraints
    MIN_LENGTH = 3
    MAX_LENGTH = 63
    HASH_PREFIX_LENGTH = 16  # Use first 16 chars of hash for uniqueness
    
    @classmethod
    def _sanitize_name(cls, name: str) -> str:
        """Sanitize collection name to meet ChromaDB requirements."""
        # Replace invalid characters with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
        # Remove consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Ensure starts and ends with alphanumeric
        sanitized = sanitized.strip('_-')
        # Truncate to max length
        if len(sanitized) > cls.MAX_LENGTH:
            sanitized = sanitized[:cls.MAX_LENGTH].rstrip('_-')
        # Ensure minimum length
        if len(sanitized) < cls.MIN_LENGTH:
            sanitized = f"col_{sanitized}"
        return sanitized
    
    @classmethod
    def for_document(cls, file_hash: str, course_id: Optional[int] = None) -> str:
        """
        Generate collection name for a document.
        
        Args:
            file_hash: MD5 hash of the file content
            course_id: Optional Canvas course ID
            
        Returns:
            Deterministic collection name
        """
        hash_prefix = file_hash[:cls.HASH_PREFIX_LENGTH]
        
        if course_id is not None:
            name = f"canvas_{course_id}_{hash_prefix}"
        else:
            name = f"doc_{hash_prefix}"
        
        return cls._sanitize_name(name)
    
    @classmethod
    def for_file(cls, file_hash: str) -> str:
        """Generate collection name for a regular uploaded file."""
        return cls.for_document(file_hash, course_id=None)
    
    @classmethod
    def for_canvas_file(cls, file_hash: str, course_id: int) -> str:
        """Generate collection name for a Canvas-sourced file."""
        return cls.for_document(file_hash, course_id=course_id)


class CollectionRegistry:
    """
    Persistent registry of document collections.
    
    Tracks:
    - Which files have been indexed
    - Collection names for each file
    - Metadata for each collection
    """
    
    def __init__(self, registry_path: str):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._registry: Dict[str, CollectionMetadata] = {}
        self._load()
    
    def _load(self):
        """Load registry from disk."""
        try:
            if self.registry_path.exists():
                self._last_mtime = self.registry_path.stat().st_mtime
                with open(self.registry_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for key, meta_dict in data.items():
                        self._registry[key] = CollectionMetadata(**meta_dict)
                logger.info(f"Loaded collection registry with {len(self._registry)} entries")
        except Exception as e:
            logger.warning(f"Could not load collection registry: {e}")
            self._registry = {}

    def reload(self):
        """Reload registry from disk, picking up cross-process changes."""
        with self._lock:
            self._registry.clear()
            self._load()
    
    @staticmethod
    def _make_key(file_hash: str, user_id: Optional[str] = None) -> str:
        """Create composite registry key: '{user_id}:{file_hash}' or '{file_hash}' for legacy."""
        if user_id:
            return f"{user_id}:{file_hash}"
        return file_hash

    def _save(self):
        """Save registry to disk atomically.
        
        Uses write-to-temp + os.replace() to prevent corruption when
        multiple processes (e.g., worker-rag and backend) write concurrently.
        os.replace() is atomic on POSIX and near-atomic on Windows/NTFS.
        """
        try:
            data = {
                key: {
                    'collection_name': meta.collection_name,
                    'file_hash': meta.file_hash,
                    'filename': meta.filename,
                    'course_id': meta.course_id,
                    'created_at': meta.created_at,
                    'updated_at': meta.updated_at,
                    'chunk_count': meta.chunk_count,
                    'is_indexed': meta.is_indexed,
                    'user_id': meta.user_id,
                }
                for key, meta in self._registry.items()
            }
            # Write to a temp file in the same directory, then atomically replace.
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.registry_path.parent), suffix='.tmp'
            )
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(self.registry_path))
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.error(f"Could not save collection registry: {e}")
    
    def get(self, file_hash: str, user_id: Optional[str] = None) -> Optional[CollectionMetadata]:
        """Get collection metadata by file hash (scoped to user when provided)."""
        with self._lock:
            key = self._make_key(file_hash, user_id)
            return self._registry.get(key)
    
    def register(
        self,
        file_hash: str,
        filename: str,
        collection_name: str,
        course_id: Optional[int] = None,
        chunk_count: int = 0,
        user_id: Optional[str] = None,
    ) -> CollectionMetadata:
        """Register a new or updated collection."""
        with self._lock:
            key = self._make_key(file_hash, user_id)
            existing = self._registry.get(key)
            if existing:
                existing.updated_at = datetime.now().isoformat()
                existing.chunk_count = chunk_count
                existing.is_indexed = True
                self._save()
                return existing
            
            meta = CollectionMetadata(
                collection_name=collection_name,
                file_hash=file_hash,
                filename=filename,
                course_id=course_id,
                chunk_count=chunk_count,
                is_indexed=True,
                user_id=user_id,
            )
            self._registry[key] = meta
            self._save()
            return meta
    
    def unregister(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """Remove a collection entry from registry for a specific user."""
        with self._lock:
            key = self._make_key(file_hash, user_id)
            if key in self._registry:
                del self._registry[key]
                self._save()
                return True
            return False
    
    def count_references(self, file_hash: str) -> int:
        """Count how many registry entries reference the same file_hash (across users)."""
        with self._lock:
            return sum(1 for meta in self._registry.values() if meta.file_hash == file_hash)
    
    def is_indexed(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a file is already indexed (scoped to user when provided)."""
        with self._lock:
            key = self._make_key(file_hash, user_id)
            meta = self._registry.get(key)
            return meta is not None and meta.is_indexed
    
    def get_collection_name(self, file_hash: str, user_id: Optional[str] = None) -> Optional[str]:
        """Get collection name for a file hash."""
        with self._lock:
            key = self._make_key(file_hash, user_id)
            meta = self._registry.get(key)
            return meta.collection_name if meta else None
    
    def get_all(self, user_id: Optional[str] = None) -> List[CollectionMetadata]:
        """Get all registered collections, filtered by user when provided."""
        with self._lock:
            if user_id is None:
                return list(self._registry.values())
            return [
                meta for meta in self._registry.values()
                if meta.user_id == user_id
            ]
    
    def get_by_user(self, user_id: str) -> List[CollectionMetadata]:
        """Get all collections belonging to a specific user."""
        with self._lock:
            return [
                meta for meta in self._registry.values()
                if meta.user_id == user_id
            ]
    
    def get_by_filenames(self, filenames: List[str], user_id: Optional[str] = None) -> List[CollectionMetadata]:
        """Get collections for specific filenames, scoped to user when provided."""
        with self._lock:
            return [
                meta for meta in self._registry.values()
                if meta.filename in filenames
                and (user_id is None or meta.user_id == user_id)
            ]
    
    def get_by_course_id(self, course_id: int) -> List[CollectionMetadata]:
        """Get all collections for a specific course."""
        with self._lock:
            return [
                meta for meta in self._registry.values()
                if meta.course_id == course_id
            ]
    
    def clear(self, user_id: Optional[str] = None):
        """Clear registry entries. If user_id given, only clear that user's entries."""
        with self._lock:
            if user_id is None:
                self._registry.clear()
            else:
                keys_to_remove = [
                    key for key, meta in self._registry.items()
                    if meta.user_id == user_id
                ]
                for key in keys_to_remove:
                    del self._registry[key]
            self._save()


class PerFileCollectionManager:
    """
    Manages per-file ChromaDB collections.
    
    Features:
    - Per-file collection isolation (no global write locks)
    - Thread-safe access with granular locking per collection
    - Shared embedding model across all collections
    - Collection lifecycle management (create, get, delete)
    
    This is the core component that enables concurrent multi-user indexing.
    """
    
    _embedding_model: Optional[HuggingFaceEmbeddings] = None
    _embedding_lock = threading.Lock()
    
    def __init__(
        self,
        persist_directory: str,
        registry_path: Optional[str] = None,
        embedding_model: Optional[str] = None,
        device: Optional[str] = None
    ):
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        
        self.embedding_model_name = embedding_model or rag_config.EMBEDDING_MODEL
        self.device = device or rag_config.EMBEDDING_DEVICE
        
        # Registry
        registry_file = registry_path or str(self.persist_directory / "collection_registry.json")
        self.registry = CollectionRegistry(registry_file)
        
        # Per-collection locks for thread safety
        self._collection_locks: Dict[str, threading.RLock] = {}
        self._locks_lock = threading.Lock()
        
        # Collection cache (avoid repeated ChromaDB client creation)
        self._collections: Dict[str, Chroma] = {}
        
        # Initialize shared embedding model
        self._init_embeddings()
        
        # Clean up orphaned directories on startup
        self._cleanup_orphaned_directories()
    
    def _cleanup_orphaned_directories(self):
        """
        Clean up collection directories that are not in the registry.
        This handles cases where file deletion failed due to locking.
        """
        try:
            import shutil
            
            # Get all registered collection names
            registered_names = {meta.collection_name for meta in self.registry.get_all()}
            
            # Find directories that look like collections
            for item in self.persist_directory.iterdir():
                if not item.is_dir():
                    continue
                    
                # Skip non-collection directories (like the registry file's parent)
                name = item.name
                if not (name.startswith('canvas_') or name.startswith('doc_')):
                    continue
                
                # If directory exists but not in registry, it's orphaned
                if name not in registered_names:
                    try:
                        shutil.rmtree(item)
                        logger.debug(f"Cleaned up orphaned collection directory: {name}")
                    except Exception as e:
                        logger.warning(f"Could not clean up orphaned directory {name}: {e}")
        except Exception as e:
            logger.warning(f"Error during orphaned directory cleanup: {e}")
    
    def ensure_fresh_state(self):
        """
        Ensure this manager's in-memory state reflects what's on disk.

        With --pool=threads, intra-worker state is always fresh. This method
        is kept as defense-in-depth for:
        - FastAPI backend process (separate process, may have stale registry)
        - Future architecture changes (if workers are ever split again)
        - Orphaned directory cleanup

        Optimization: skip reload if registry file hasn't changed since last load.

        IMPORTANT: The _locks_lock guard below is the Phase 0.1 thread-safety fix.
        It prevents races with get_or_create_collection() on the _collections dict.
        Do NOT remove it — see WORKER_MERGE_PLAN.md Section 9.1, Issue 1.
        """
        with self._locks_lock:
            # Quick mtime check — skip reload if file hasn't changed
            try:
                disk_mtime = self.registry.registry_path.stat().st_mtime
                if hasattr(self.registry, '_last_mtime') and disk_mtime == self.registry._last_mtime:
                    self._cleanup_orphaned_directories()
                    return
            except (OSError, AttributeError):
                pass  # Fall through to full reload

            self.registry.reload()

            # Evict cached Chroma instances whose collection names are no longer
            # present in the freshly-reloaded registry.
            registered_names = {meta.collection_name for meta in self.registry.get_all()}
            stale_keys = [k for k in self._collections if k not in registered_names]
            for key in stale_keys:
                old = self._collections.pop(key, None)
                if old is not None:
                    try:
                        if hasattr(old, '_client'):
                            del old._client
                        del old
                    except Exception:
                        pass
                logger.debug(f"Evicted stale cached collection: {key}")

            if stale_keys:
                import gc
                gc.collect()

        self._cleanup_orphaned_directories()
    
    def _init_embeddings(self):
        """Initialize shared embedding model (singleton, shared with ChromaVectorStore)."""
        with PerFileCollectionManager._embedding_lock:
            if PerFileCollectionManager._embedding_model is None:
                # Check if ChromaVectorStore already loaded it
                try:
                    from .vectorstore import ChromaVectorStore
                    if ChromaVectorStore._embedding_model is not None:
                        logger.info("Reusing embedding model from ChromaVectorStore")
                        PerFileCollectionManager._embedding_model = ChromaVectorStore._embedding_model
                        self.embeddings = PerFileCollectionManager._embedding_model
                        return
                except ImportError:
                    pass

                logger.info(f"Loading embedding model: {self.embedding_model_name}")
                logger.info(f"Using device: {self.device}")
                
                PerFileCollectionManager._embedding_model = HuggingFaceEmbeddings(
                    model_name=self.embedding_model_name,
                    model_kwargs={'device': self.device},
                    encode_kwargs={'normalize_embeddings': rag_config.NORMALIZE_EMBEDDINGS}
                )
                logger.info("Embedding model loaded successfully")

                # Share with ChromaVectorStore so it doesn't reload
                try:
                    from .vectorstore import ChromaVectorStore
                    if ChromaVectorStore._embedding_model is None:
                        ChromaVectorStore._embedding_model = PerFileCollectionManager._embedding_model
                except ImportError:
                    pass
            
            self.embeddings = PerFileCollectionManager._embedding_model
    
    def _get_collection_lock(self, collection_name: str) -> threading.RLock:
        """Get or create a lock for a specific collection."""
        with self._locks_lock:
            if collection_name not in self._collection_locks:
                self._collection_locks[collection_name] = threading.RLock()
            return self._collection_locks[collection_name]
    
    def get_collection_name(
        self,
        file_hash: str,
        course_id: Optional[int] = None
    ) -> str:
        """
        Get deterministic collection name for a file.
        
        Args:
            file_hash: MD5 hash of the file
            course_id: Optional Canvas course ID
            
        Returns:
            Deterministic collection name
        """
        return CollectionNameGenerator.for_document(file_hash, course_id)
    
    def get_or_create_collection(
        self,
        file_hash: str,
        filename: str,
        course_id: Optional[int] = None
    ) -> Tuple[Chroma, str]:
        """
        Get existing collection or create new one for a file.
        
        Args:
            file_hash: MD5 hash of the file
            filename: Original filename
            course_id: Optional Canvas course ID
            
        Returns:
            Tuple of (Chroma collection, collection_name)
        """
        # First check if we already have metadata for this file in registry
        # This ensures we use the correct collection name for existing files
        meta = self.registry.get(file_hash)
        if meta:
            collection_name = meta.collection_name
        else:
            # New file - generate collection name
            collection_name = self.get_collection_name(file_hash, course_id)
        
        lock = self._get_collection_lock(collection_name)
        
        with lock:
            # Check cache first
            if collection_name in self._collections:
                return self._collections[collection_name], collection_name
            
            # Create or load collection
            collection_dir = str(self.persist_directory / collection_name)
            Path(collection_dir).mkdir(parents=True, exist_ok=True)
            
            logger.debug(f"Getting/creating collection: {collection_name} for file: {filename}")
            
            collection = Chroma(
                collection_name=collection_name,
                embedding_function=self.embeddings,
                persist_directory=collection_dir
            )
            
            # Cache it
            self._collections[collection_name] = collection
            
            return collection, collection_name
    
    def add_documents(
        self,
        file_hash: str,
        filename: str,
        documents: List[Document],
        course_id: Optional[int] = None,
        replace_existing: bool = True,
        user_id: Optional[str] = None,
    ) -> int:
        """
        Add documents to a file's collection.
        
        Args:
            file_hash: MD5 hash of the file
            filename: Original filename
            documents: List of Document objects to add
            course_id: Optional Canvas course ID
            replace_existing: If True, clear existing docs before adding
            user_id: Optional user ID for per-user registry tracking
            
        Returns:
            Number of documents added
        """
        if not documents:
            logger.warning("No documents to add")
            return 0
        
        collection, collection_name = self.get_or_create_collection(
            file_hash, filename, course_id
        )
        lock = self._get_collection_lock(collection_name)
        
        with lock:
            # If replacing, clear existing documents
            if replace_existing:
                try:
                    count = collection._collection.count()
                    if count > 0:
                        logger.debug(f"Replacing {count} existing documents in {collection_name}")
                        # Get all IDs and delete them
                        existing = collection._collection.get(include=[])
                        if existing and existing.get("ids"):
                            collection._collection.delete(ids=existing["ids"])
                except Exception as e:
                    logger.warning(f"Could not clear existing documents: {e}")
            
            # Generate unique IDs for documents
            ids = [
                f"{file_hash}_{i}_{doc.metadata.get('doc_id', i)}"
                for i, doc in enumerate(documents)
            ]
            
            # Add documents
            logger.debug(f"Adding {len(documents)} documents to collection: {collection_name}")
            collection.add_documents(documents=documents, ids=ids)
            
            # Update registry
            self.registry.register(
                file_hash=file_hash,
                filename=filename,
                collection_name=collection_name,
                course_id=course_id,
                chunk_count=len(documents),
                user_id=user_id,
            )
            
            logger.debug(f"Successfully added {len(documents)} documents to {collection_name}")
            return len(documents)
    
    def query_collection(
        self,
        file_hash: str,
        query: str,
        k: int = 4,
        course_id: Optional[int] = None,
        **kwargs
    ) -> List[Document]:
        """
        Query a specific file's collection.
        
        Args:
            file_hash: MD5 hash of the file to query
            query: Search query
            k: Number of results to return
            course_id: Optional Canvas course ID
            
        Returns:
            List of relevant Document objects
        """
        # First try to get collection name and course_id from registry
        # This ensures we use the correct collection name even if course_id isn't passed
        meta = self.registry.get(file_hash)
        if not meta:
            # Registry may be stale in multi-process Docker (e.g., worker-llm
            # hasn't seen backend's ingest). Reload once from disk before
            # falling back to generated name, which would produce the WRONG
            # name (doc_* instead of canvas_*) and create an empty collection.
            self.registry.reload()
            meta = self.registry.get(file_hash)
        if meta:
            collection_name = meta.collection_name
            actual_course_id = meta.course_id
        else:
            # Fallback to generating collection name
            logger.warning(
                f"Registry miss for {file_hash[:8]} even after reload — "
                f"falling back to generated name (course_id={course_id})"
            )
            collection_name = self.get_collection_name(file_hash, course_id)
            actual_course_id = course_id
        
        if collection_name not in self._collections:
            # Try to load the collection
            try:
                collection, _ = self.get_or_create_collection(
                    file_hash, meta.filename if meta else "unknown", actual_course_id
                )
            except Exception as e:
                logger.warning(f"Could not load collection {collection_name}: {e}")
                return []
        else:
            collection = self._collections[collection_name]
        
        return collection.similarity_search(query, k=k, **kwargs)
    
    def query_multiple_collections(
        self,
        file_hashes: List[str],
        query: str,
        k: int = 4,
        course_id: Optional[int] = None,
        **kwargs
    ) -> List[Document]:
        """
        Query multiple file collections and merge results.
        
        Args:
            file_hashes: List of file hashes to query
            query: Search query
            k: Number of results PER COLLECTION
            course_id: Optional Canvas course ID
            
        Returns:
            Merged list of relevant Document objects
        """
        all_results = []
        
        for file_hash in file_hashes:
            try:
                results = self.query_collection(
                    file_hash=file_hash,
                    query=query,
                    k=k,
                    course_id=course_id,
                    **kwargs
                )
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Error querying collection for {file_hash}: {e}")
        
        # Sort by relevance if scores are available
        # For now, just return combined results
        return all_results
    
    def get_retriever(
        self,
        file_hash: str,
        course_id: Optional[int] = None,
        search_type: str = "mmr",
        search_kwargs: Optional[Dict] = None
    ):
        """
        Get a retriever for a specific file's collection.
        
        Args:
            file_hash: MD5 hash of the file
            course_id: Optional Canvas course ID
            search_type: "mmr" or "similarity"
            search_kwargs: Additional search parameters
            
        Returns:
            Langchain retriever object
        """
        # Get metadata from registry to use correct collection name
        meta = self.registry.get(file_hash)
        if meta:
            actual_course_id = meta.course_id
            filename = meta.filename
        else:
            actual_course_id = course_id
            filename = "unknown"
        
        collection, collection_name = self.get_or_create_collection(
            file_hash, filename, actual_course_id
        )
        
        if search_kwargs is None:
            search_kwargs = {
                "k": rag_config.RETRIEVER_K,
                "fetch_k": rag_config.RETRIEVER_FETCH_K,
                "lambda_mult": rag_config.RETRIEVER_LAMBDA_MULT
            }
        
        return collection.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )
    
    def is_indexed(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if a file is already indexed (optionally for a specific user)."""
        return self.registry.is_indexed(file_hash, user_id=user_id)
    
    def get_indexed_files(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of indexed files, optionally filtered by user."""
        return [
            {
                'filename': meta.filename,
                'file_hash': meta.file_hash,
                'collection_name': meta.collection_name,
                'course_id': meta.course_id,
                'chunk_count': meta.chunk_count,
                'indexed_at': meta.created_at,
                'updated_at': meta.updated_at,
                'user_id': meta.user_id,
            }
            for meta in self.registry.get_all(user_id=user_id)
        ]
    
    def get_collection_stats(self, file_hash: str) -> Dict[str, Any]:
        """Get statistics for a specific file's collection."""
        meta = self.registry.get(file_hash)
        if not meta:
            return {"error": "Collection not found"}
        
        stats = {
            "collection_name": meta.collection_name,
            "filename": meta.filename,
            "file_hash": meta.file_hash,
            "chunk_count": meta.chunk_count,
            "is_indexed": meta.is_indexed,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at
        }
        
        # Get actual count from collection
        try:
            collection, _ = self.get_or_create_collection(
                file_hash, meta.filename, meta.course_id
            )
            stats["actual_document_count"] = collection._collection.count()
        except Exception as e:
            logger.warning(f"Could not get collection count: {e}")
        
        return stats
    
    def delete_collection(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Delete a file's collection.
        If user_id is given, only removes that user's registry entry.
        Actual ChromaDB collection is only deleted when no users reference it.
        
        Args:
            file_hash: MD5 hash of the file
            user_id: Optional user who owns this entry
            
        Returns:
            True if deleted successfully (or marked for cleanup)
        """
        meta = self.registry.get(file_hash, user_id=user_id)
        if not meta:
            logger.warning(f"Cannot delete collection: file_hash {file_hash} not found in registry")
            return False
        
        collection_name = meta.collection_name
        lock = self._get_collection_lock(collection_name)
        
        with lock:
            # 1. First, unregister from registry (most important - prevents listing)
            self.registry.unregister(file_hash, user_id=user_id)
            logger.info(f"Unregistered collection from registry: {collection_name} (user={user_id})")
            
            # 2. Only delete actual ChromaDB data if no other users reference this hash
            remaining_refs = self.registry.count_references(file_hash)
            if remaining_refs > 0:
                logger.info(f"Collection {collection_name} still referenced by {remaining_refs} user(s), keeping data")
                return True
            
            # 2. Remove from in-memory cache — explicitly release Chroma/SQLite handles
            if collection_name in self._collections:
                old_collection = self._collections.pop(collection_name)
                try:
                    # Release the underlying SQLite connections held by Chroma
                    if hasattr(old_collection, '_client'):
                        del old_collection._client
                    del old_collection
                except Exception:
                    pass
            
            # 3. Force GC to release SQLite handles before deleting directory.
            #    DO NOT create a temporary PersistentClient here — it opens new
            #    SQLite handles on the same directory, which prevents rmtree
            #    from succeeding (PermissionError on Windows/Docker).
            import gc
            gc.collect()
            
            # 4. Try to delete the collection directory directly
            try:
                import shutil
                
                collection_dir = self.persist_directory / collection_name
                if collection_dir.exists():
                    shutil.rmtree(collection_dir)
                    logger.info(f"Deleted collection directory: {collection_name}")
            except PermissionError as e:
                # Files are locked (e.g., by another process) - log but continue.
                # The registry is already cleared, so _cleanup_orphaned_directories()
                # will retry on next startup or after the caller invokes it.
                logger.warning(f"Could not delete directory {collection_name} (files locked): {e}")
            except Exception as e:
                logger.warning(f"Could not delete collection directory: {e}")
            
            logger.info(f"Deleted collection: {collection_name}")
            return True
    
    def get_all_document_content(
        self,
        file_hash: Optional[str] = None,
        max_docs: int = 50,
        user_id: Optional[str] = None,
    ) -> List[str]:
        """
        Get document content from collections.
        
        Args:
            file_hash: If provided, get content from specific file only.
                      If None, get content from all indexed files.
            max_docs: Maximum number of documents to retrieve.
            user_id: Optional user ID to scope to user's files only.
            
        Returns:
            List of document content strings
        """
        contents = []
        
        if file_hash:
            # Get content from specific file
            file_hashes = [file_hash]
        else:
            # Get content from all indexed files (optionally filtered by user)
            file_hashes = [meta.file_hash for meta in self.registry.get_all(user_id=user_id)]
        
        for fh in file_hashes:
            if len(contents) >= max_docs:
                break
                
            meta = self.registry.get(fh)
            if not meta:
                continue
            
            try:
                collection, _ = self.get_or_create_collection(
                    fh, meta.filename, meta.course_id
                )
                
                # Get all documents from collection
                result = collection.get(include=["documents"])
                if result and result.get("documents"):
                    for doc in result["documents"]:
                        if len(contents) >= max_docs:
                            break
                        if doc:
                            contents.append(doc)
                            
            except Exception as e:
                logger.warning(f"Could not get content from collection for {fh}: {e}")
                continue
        
        return contents

    def reset_all(self, user_id: Optional[str] = None) -> bool:
        """
        Delete all collections and reset registry.
        If user_id is given, only reset that user's data.
        
        Returns:
            True if reset successful
        """
        if user_id:
            logger.warning(f"Resetting collections for user {user_id}")
        else:
            logger.warning("Resetting all collections")
        
        try:
            if user_id:
                # Only remove user's registry entries; delete ChromaDB data only if no other refs
                user_entries = self.registry.get_by_user(user_id)
                for meta in user_entries:
                    self.delete_collection(meta.file_hash, user_id=user_id)
                return True
            
            # Clear all cached collections
            for collection_name in list(self._collections.keys()):
                try:
                    collection = self._collections.pop(collection_name)
                    client = collection._client
                    client.delete_collection(collection_name)
                except Exception as e:
                    logger.warning(f"Could not delete collection {collection_name}: {e}")
            
            # Clear persist directory
            import shutil
            for item in self.persist_directory.iterdir():
                if item.is_dir() and item.name != "__pycache__":
                    shutil.rmtree(item)
                elif item.is_file() and item.name.endswith('.json'):
                    item.unlink()
            
            # Clear registry
            self.registry.clear()
            
            logger.info("All collections reset successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting collections: {e}")
            return False


# ===== Singleton Instance Management =====

_manager_instances: Dict[str, PerFileCollectionManager] = {}
_manager_lock = threading.Lock()


def get_collection_manager(
    persist_directory: Optional[str] = None,
    manager_key: str = "default"
) -> PerFileCollectionManager:
    """
    Get or create a PerFileCollectionManager instance.
    
    Args:
        persist_directory: Directory for persistent storage
        manager_key: Key to identify manager instance (e.g., "uploads", "canvas")
        
    Returns:
        PerFileCollectionManager instance
    """
    with _manager_lock:
        if manager_key not in _manager_instances:
            directory = persist_directory or rag_config.PERSIST_DIRECTORY
            _manager_instances[manager_key] = PerFileCollectionManager(
                persist_directory=directory
            )
            logger.info(f"Created collection manager: {manager_key}")
        
        return _manager_instances[manager_key]


def get_uploads_collection_manager() -> PerFileCollectionManager:
    """Get the collection manager for regular uploads."""
    return get_collection_manager(
        persist_directory=rag_config.PERSIST_DIRECTORY,
        manager_key="uploads"
    )


def get_canvas_collection_manager() -> PerFileCollectionManager:
    """Get the collection manager for Canvas files."""
    canvas_dir = "./data/chroma/canvas_document_rag"
    return get_collection_manager(
        persist_directory=canvas_dir,
        manager_key="canvas"
    )
