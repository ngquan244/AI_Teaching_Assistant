"""
Topic Storage Module
====================
Stores extracted topics per document for quick retrieval.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from .config import rag_config

logger = logging.getLogger(__name__)


class TopicStorage:
    """
    Persistent storage for document topics.
    Topics are extracted once during indexing and stored for quick retrieval.
    Supports per-user isolation via composite keys '{user_id}:{file_hash}'.
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize topic storage.
        
        Args:
            storage_dir: Directory to store topic data
        """
        self.storage_dir = Path(storage_dir or rag_config.PERSIST_DIRECTORY)
        self.storage_file = self.storage_dir / "document_topics.json"
        self._topics: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        
        # Ensure directory exists
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing topics
        self._load()
    
    @staticmethod
    def _make_key(file_hash: str, user_id: Optional[str] = None) -> str:
        """Create composite key: '{user_id}:{file_hash}' or '{file_hash}' for legacy."""
        if user_id:
            return f"{user_id}:{file_hash}"
        return file_hash
    
    def _load(self):
        """Load topics from disk."""
        with self._lock:
            try:
                if self.storage_file.exists():
                    with open(self.storage_file, 'r', encoding='utf-8') as f:
                        self._topics = json.load(f)
                    logger.info(f"Loaded topics for {len(self._topics)} documents")
            except Exception as e:
                logger.warning(f"Could not load topics: {e}")
                self._topics = {}
    
    def _save(self):
        """Save topics to disk."""
        with self._lock:
            try:
                with open(self.storage_file, 'w', encoding='utf-8') as f:
                    json.dump(self._topics, f, ensure_ascii=False, indent=2)
                logger.info(f"Saved topics for {len(self._topics)} documents")
            except Exception as e:
                logger.error(f"Could not save topics: {e}")
    
    def save_topics(
        self,
        file_hash: str,
        filename: str,
        topics: List[Dict[str, str]],
        user_id: Optional[str] = None,
    ):
        """
        Save topics for a document.
        
        Args:
            file_hash: MD5 hash of the document
            filename: Original filename
            topics: List of topic dictionaries with 'name' and 'description'
            user_id: Optional user ID for per-user scoping
        """
        key = self._make_key(file_hash, user_id)
        with self._lock:
            self._topics[key] = {
                "filename": filename,
                "topics": topics,
                "extracted_at": datetime.now().isoformat(),
                "user_id": user_id,
            }
        self._save()
        logger.info(f"Saved {len(topics)} topics for {filename} (user={user_id})")
    
    def get_topics(self, file_hash: str, user_id: Optional[str] = None) -> Optional[List[Dict[str, str]]]:
        """
        Get topics for a document.
        
        Args:
            file_hash: MD5 hash of the document
            user_id: Optional user ID for per-user scoping
            
        Returns:
            List of topics or None if not found
        """
        key = self._make_key(file_hash, user_id)
        with self._lock:
            if key in self._topics:
                return self._topics[key].get("topics", [])
        return None
    
    def get_topics_by_filename(
        self, filename: str, user_id: Optional[str] = None
    ) -> Optional[List[Dict[str, str]]]:
        """
        Get topics by filename, optionally scoped to user.
        
        Args:
            filename: Document filename
            user_id: Optional user ID for per-user scoping
            
        Returns:
            List of topics or None if not found
        """
        for key, data in self._topics.items():
            if data.get("filename") == filename:
                entry_user = data.get("user_id")
                if user_id is None or entry_user == user_id:
                    return data.get("topics", [])
        return None
    
    def has_topics(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """Check if topics exist for a document."""
        key = self._make_key(file_hash, user_id)
        with self._lock:
            return key in self._topics
    
    def get_all_documents(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get list of all documents with topics, optionally filtered by user.
        
        Returns:
            List of document info dictionaries
        """
        documents = []
        with self._lock:
            for key, data in self._topics.items():
                entry_user = data.get("user_id")
                if user_id is not None and entry_user != user_id:
                    continue
                # Extract file_hash from composite key
                if ":" in key:
                    file_hash = key.split(":", 1)[1]
                else:
                    file_hash = key
                documents.append({
                    "file_hash": file_hash,
                    "filename": data.get("filename", "unknown"),
                    "topic_count": len(data.get("topics", [])),
                    "extracted_at": data.get("extracted_at"),
                    "user_id": entry_user,
                })
        return documents
    
    def remove_document(self, file_hash: str, user_id: Optional[str] = None) -> bool:
        """
        Remove topics for a document.
        
        Args:
            file_hash: MD5 hash of the document
            user_id: Optional user ID to scope removal
            
        Returns:
            True if removed, False if not found
        """
        key = self._make_key(file_hash, user_id)
        with self._lock:
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
        """
        Update topics for a document by filename.
        
        Args:
            filename: Document filename
            topics: New list of topic dictionaries with 'name' and optionally 'description'
            user_id: Optional user ID to scope update
            
        Returns:
            True if updated, False if not found
        """
        with self._lock:
            for key, data in self._topics.items():
                if data.get("filename") == filename:
                    entry_user = data.get("user_id")
                    if user_id is None or entry_user == user_id:
                        self._topics[key]["topics"] = topics
                        self._topics[key]["updated_at"] = datetime.now().isoformat()
                        self._save()
                        logger.info(f"Updated {len(topics)} topics for {filename}")
                        return True
        return False
    
    def clear(self, user_id: Optional[str] = None):
        """Clear stored topics. If user_id given, only clear that user's topics."""
        with self._lock:
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
        logger.info(f"Cleared stored topics (user={user_id})")


# Global instance
topic_storage = TopicStorage()
