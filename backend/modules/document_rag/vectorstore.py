"""
Vector Store Module
===================
ChromaDB vector store with persistence support.
Uses HuggingFace embeddings (BAAI/bge-m3) as specified in RAG_AI_Tutor.ipynb.
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Set, Dict, Any

from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma

from .config import rag_config

logger = logging.getLogger(__name__)


class ChromaVectorStore:
    """
    ChromaDB vector store with persistent storage.
    
    Features:
    - Persistent storage to disk
    - Document deduplication via doc_id
    - Embedding using BAAI/bge-m3 (from RAG_AI_Tutor.ipynb)
    """
    
    _embedding_model: Optional[HuggingFaceEmbeddings] = None
    
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
        embedding_model: Optional[str] = None,
        device: Optional[str] = None
    ):
        """
        Initialize ChromaDB vector store.
        
        Args:
            persist_directory: Directory for persistent storage
            collection_name: Name of the collection
            embedding_model: HuggingFace embedding model name
            device: Device to use for embeddings ('cpu' or 'cuda')
        """
        self.persist_directory = persist_directory or rag_config.PERSIST_DIRECTORY
        self.collection_name = collection_name or rag_config.COLLECTION_NAME
        self.embedding_model_name = embedding_model or rag_config.EMBEDDING_MODEL
        self.device = device or rag_config.EMBEDDING_DEVICE
        
        # Ensure persist directory exists
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding model (cached)
        self._init_embeddings()
        
        # Initialize or load vector store
        self._vector_store: Optional[Chroma] = None
        self._load_or_create_store()
        
        # Track indexed document hashes
        self._indexed_hashes: Set[str] = set()
        self._load_indexed_hashes()
    
    def _init_embeddings(self):
        """Initialize HuggingFace embeddings model (singleton, shared with PerFileCollectionManager)."""
        from .collection_manager import PerFileCollectionManager

        with PerFileCollectionManager._embedding_lock:
            if ChromaVectorStore._embedding_model is None:
                # Check if PerFileCollectionManager already loaded it
                if PerFileCollectionManager._embedding_model is not None:
                    logger.info("Reusing embedding model from PerFileCollectionManager")
                    ChromaVectorStore._embedding_model = PerFileCollectionManager._embedding_model
                    self.embeddings = ChromaVectorStore._embedding_model
                    return

                logger.info(f"Loading embedding model: {self.embedding_model_name}")
                logger.info(f"Using device: {self.device}")
                
                ChromaVectorStore._embedding_model = HuggingFaceEmbeddings(
                    model_name=self.embedding_model_name,
                    model_kwargs={'device': self.device},
                    encode_kwargs={'normalize_embeddings': rag_config.NORMALIZE_EMBEDDINGS}
                )
                
                logger.info("Embedding model loaded successfully")

                # Share with PerFileCollectionManager so it doesn't reload
                if PerFileCollectionManager._embedding_model is None:
                    PerFileCollectionManager._embedding_model = ChromaVectorStore._embedding_model
            
            self.embeddings = ChromaVectorStore._embedding_model
    
    def _load_or_create_store(self):
        """Load existing vector store or create new one."""
        persist_path = Path(self.persist_directory)
        
        if persist_path.exists() and any(persist_path.iterdir()):
            logger.info(f"Loading existing vector store from: {self.persist_directory}")
            self._vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory
            )
        else:
            logger.info(f"Creating new vector store at: {self.persist_directory}")
            self._vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=self.persist_directory
            )
    
    def _load_indexed_hashes(self):
        """Load set of already indexed document hashes."""
        try:
            if self._vector_store:
                # Get all documents from collection
                collection = self._vector_store._collection
                result = collection.get(include=["metadatas"])
                
                if result and result.get("metadatas"):
                    for meta in result["metadatas"]:
                        if meta and "file_hash" in meta:
                            self._indexed_hashes.add(meta["file_hash"])
                
                logger.debug(f"Loaded {len(self._indexed_hashes)} indexed document hashes")
        except Exception as e:
            logger.warning(f"Could not load indexed hashes: {e}")
            self._indexed_hashes = set()
    
    def _save_indexed_hashes(self):
        """Save indexed hashes (no-op as hashes are stored in collection metadata)."""
        # Indexed hashes are derived from collection metadata, no separate save needed
        pass
    
    def is_document_indexed(self, file_hash: str) -> bool:
        """
        Check if a document with given hash is already indexed.
        
        Args:
            file_hash: MD5 hash of the document file
            
        Returns:
            True if document is already indexed
        """
        return file_hash in self._indexed_hashes
    
    def add_documents(
        self,
        documents: List[Document],
        skip_duplicates: bool = True
    ) -> int:
        """
        Add documents to the vector store.
        
        Args:
            documents: List of Document objects to add
            skip_duplicates: Skip documents that are already indexed
            
        Returns:
            Number of documents actually added
        """
        if not documents:
            logger.warning("No documents to add")
            return 0
        
        # Filter duplicates if requested
        docs_to_add = documents
        if skip_duplicates:
            docs_to_add = []
            for doc in documents:
                file_hash = doc.metadata.get("file_hash", "")
                if file_hash and file_hash in self._indexed_hashes:
                    continue
                docs_to_add.append(doc)
            
            if len(docs_to_add) < len(documents):
                logger.debug(f"Skipped {len(documents) - len(docs_to_add)} duplicate documents")
        
        if not docs_to_add:
            logger.info("All documents already indexed, nothing to add")
            return 0
        
        # Add to vector store
        logger.debug(f"Adding {len(docs_to_add)} documents to vector store")
        
        # Generate IDs for documents
        ids = [
            doc.metadata.get("doc_id", f"doc_{i}") 
            for i, doc in enumerate(docs_to_add)
        ]
        
        self._vector_store.add_documents(documents=docs_to_add, ids=ids)
        
        # Update indexed hashes
        for doc in docs_to_add:
            file_hash = doc.metadata.get("file_hash", "")
            if file_hash:
                self._indexed_hashes.add(file_hash)
        
        logger.debug(f"Successfully added {len(docs_to_add)} documents")
        return len(docs_to_add)
    
    def get_retriever(self, **kwargs):
        """
        Get a retriever from the vector store.
        
        Args:
            **kwargs: Additional arguments for the retriever
            
        Returns:
            Retriever object
        """
        if not self._vector_store:
            raise RuntimeError("Vector store not initialized")
        
        search_type = kwargs.pop("search_type", rag_config.SEARCH_TYPE)
        search_kwargs = kwargs.pop("search_kwargs", {
            "k": rag_config.RETRIEVER_K,
            "fetch_k": rag_config.RETRIEVER_FETCH_K,
            "lambda_mult": rag_config.RETRIEVER_LAMBDA_MULT
        })
        
        return self._vector_store.as_retriever(
            search_type=search_type,
            search_kwargs=search_kwargs
        )
    
    def similarity_search(
        self,
        query: str,
        k: int = 4,
        **kwargs
    ) -> List[Document]:
        """
        Perform similarity search.
        
        Args:
            query: Search query
            k: Number of results to return
            **kwargs: Additional search arguments
            
        Returns:
            List of relevant Document objects
        """
        if not self._vector_store:
            raise RuntimeError("Vector store not initialized")
        
        return self._vector_store.similarity_search(query, k=k, **kwargs)
    
    def delete_by_filter(self, filter_dict: Dict[str, Any]) -> int:
        """
        Delete documents matching a filter.
        
        Args:
            filter_dict: Dictionary with metadata filters (e.g., {"file_hash": "abc123"})
            
        Returns:
            Number of documents deleted
        """
        try:
            if not self._vector_store:
                return 0
            
            collection = self._vector_store._collection
            
            # Get IDs of documents matching filter
            result = collection.get(
                where=filter_dict,
                include=[]
            )
            
            if result and result.get("ids"):
                ids_to_delete = result["ids"]
                collection.delete(ids=ids_to_delete)
                
                # Remove from indexed hashes if file_hash is in filter
                if "file_hash" in filter_dict:
                    self._indexed_hashes.discard(filter_dict["file_hash"])
                    self._save_indexed_hashes()
                
                logger.debug(f"Deleted {len(ids_to_delete)} documents matching filter: {filter_dict}")
                return len(ids_to_delete)
            
            return 0
        except Exception as e:
            logger.error(f"Error deleting by filter: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Alias for get_collection_stats for compatibility."""
        return self.get_collection_stats()
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the collection.
        
        Returns:
            Dictionary with collection statistics
        """
        stats = {
            "persist_directory": self.persist_directory,
            "collection_name": self.collection_name,
            "embedding_model": self.embedding_model_name,
            "device": self.device,
            "indexed_file_hashes": len(self._indexed_hashes),
            "total_documents": 0
        }
        
        try:
            if self._vector_store:
                collection = self._vector_store._collection
                stats["total_documents"] = collection.count()
        except Exception as e:
            logger.warning(f"Could not get collection count: {e}")
        
        return stats
    
    def get_all_document_content(self, max_docs: int = 50) -> List[str]:
        """
        Get content of all documents in the collection for topic extraction.
        
        Args:
            max_docs: Maximum number of documents to retrieve
            
        Returns:
            List of document content strings
        """
        try:
            if not self._vector_store:
                return []
            
            collection = self._vector_store._collection
            result = collection.get(
                include=["documents"],
                limit=max_docs
            )
            
            if result and result.get("documents"):
                return result["documents"]
            
            return []
        except Exception as e:
            logger.warning(f"Could not get document content: {e}")
            return []
    
    def get_indexed_files(self) -> List[Dict[str, Any]]:
        """
        Get list of indexed files with metadata.
        
        Returns:
            List of file info dictionaries
        """
        try:
            if not self._vector_store:
                return []
            
            collection = self._vector_store._collection
            result = collection.get(include=["metadatas"])
            
            if not result or not result.get("metadatas"):
                return []
            
            # Extract unique files
            files = {}
            for meta in result["metadatas"]:
                if meta:
                    filename = meta.get("filename", meta.get("source", "unknown"))
                    if filename not in files:
                        files[filename] = {
                            "filename": filename,
                            "source": meta.get("source", ""),
                            "file_hash": meta.get("file_hash", ""),
                            "chunk_count": 1
                        }
                    else:
                        files[filename]["chunk_count"] += 1
            
            return list(files.values())
            
        except Exception as e:
            logger.warning(f"Could not get indexed files: {e}")
            return []
    
    def reset_collection(self) -> bool:
        """
        Delete all documents and reset the collection.
        
        Returns:
            True if reset successful
        """
        logger.warning(f"Resetting collection: {self.collection_name}")
        
        try:
            # First, delete the collection from ChromaDB client
            if self._vector_store is not None:
                try:
                    # Get the client and delete collection
                    client = self._vector_store._client
                    client.delete_collection(self.collection_name)
                    logger.info(f"Deleted collection: {self.collection_name}")
                except Exception as e:
                    logger.warning(f"Could not delete collection: {e}")
                
                # Clear reference
                self._vector_store = None
            
            # Clear indexed hashes
            self._indexed_hashes.clear()
            
            # Recreate empty store
            self._load_or_create_store()
            
            logger.info("Collection reset complete")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting collection: {e}")
            return False
    
    @property
    def vector_store(self) -> Optional[Chroma]:
        """Get the underlying Chroma vector store."""
        return self._vector_store
