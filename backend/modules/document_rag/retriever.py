"""
Document Retriever Module
=========================
Retrieval functionality for the Document RAG system.
Includes both single-collection and multi-collection retrievers.
"""

import logging
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from langchain_core.documents import Document

from .config import rag_config
from .vectorstore import ChromaVectorStore

if TYPE_CHECKING:
    from .collection_manager import PerFileCollectionManager

logger = logging.getLogger(__name__)


class DocumentRetriever:
    """
    Document retriever with configurable search strategies.
    
    Supports:
    - MMR (Maximal Marginal Relevance) for diverse results
    - Similarity search for most relevant results
    """
    
    def __init__(
        self,
        vector_store: ChromaVectorStore,
        search_type: Optional[str] = None,
        k: Optional[int] = None,
        fetch_k: Optional[int] = None,
        lambda_mult: Optional[float] = None
    ):
        """
        Initialize retriever.
        
        Args:
            vector_store: ChromaVectorStore instance
            search_type: "mmr" or "similarity"
            k: Number of documents to retrieve
            fetch_k: Number of documents to fetch before MMR (only for MMR)
            lambda_mult: MMR diversity parameter (0=max diversity, 1=max relevance)
        """
        self.vector_store = vector_store
        self.search_type = search_type or rag_config.SEARCH_TYPE
        self.k = k or rag_config.RETRIEVER_K
        self.fetch_k = fetch_k or rag_config.RETRIEVER_FETCH_K
        self.lambda_mult = lambda_mult or rag_config.RETRIEVER_LAMBDA_MULT
    
    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        search_type: Optional[str] = None
    ) -> List[Document]:
        """
        Retrieve relevant documents for a query.
        
        Args:
            query: Search query
            k: Number of documents to retrieve (overrides default)
            search_type: Search type to use (overrides default)
            
        Returns:
            List of relevant Document objects
        """
        k = k or self.k
        search_type = search_type or self.search_type
        
        logger.info(f"Retrieving documents for query: {query[:100]}...")
        logger.info(f"Search type: {search_type}, k={k}")
        
        retriever = self.vector_store.get_retriever(
            search_type=search_type,
            search_kwargs={
                "k": k,
                "fetch_k": self.fetch_k,
                "lambda_mult": self.lambda_mult
            }
        )
        
        documents = retriever.invoke(query)
        
        logger.info(f"Retrieved {len(documents)} documents")
        
        # Log retrieved documents if debug enabled
        if rag_config.ENABLE_DEBUG_LOGGING:
            self._log_retrieved_documents(documents)
        
        return documents
    
    def retrieve_with_scores(
        self,
        query: str,
        k: Optional[int] = None
    ) -> List[tuple]:
        """
        Retrieve documents with similarity scores.
        
        Args:
            query: Search query
            k: Number of documents to retrieve
            
        Returns:
            List of (Document, score) tuples
        """
        k = k or self.k
        
        if not self.vector_store.vector_store:
            raise RuntimeError("Vector store not initialized")
        
        results = self.vector_store.vector_store.similarity_search_with_score(
            query, k=k
        )
        
        logger.info(f"Retrieved {len(results)} documents with scores")
        
        return results
    
    def _log_retrieved_documents(self, documents: List[Document]):
        """Log retrieved documents for debugging."""
        logger.info("=" * 60)
        logger.info("RETRIEVED DOCUMENTS:")
        logger.info("=" * 60)
        
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source", "unknown")
            page = doc.metadata.get("page", "?")
            snippet = doc.page_content[:rag_config.SNIPPET_LENGTH]
            
            logger.info(f"\n[{i+1}] Source: {source}, Page: {page}")
            logger.info(f"    Snippet: {snippet}...")
        
        logger.info("=" * 60)
    
    def format_context(self, documents: List[Document]) -> str:
        """
        Format retrieved documents into a context string.
        
        Args:
            documents: List of Document objects
            
        Returns:
            Formatted context string
        """
        if not documents:
            return ""
        
        context_parts = []
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source", "unknown")
            page = doc.metadata.get("page", "?")
            
            context_parts.append(
                f"[Document {i+1}] (Source: {source}, Page: {page})\n{doc.page_content}"
            )
        
        return "\n\n---\n\n".join(context_parts)
    
    def extract_citations(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Extract citation information from documents.
        
        Args:
            documents: List of Document objects
            
        Returns:
            List of citation dictionaries with source, page, and snippet
        """
        citations = []
        
        for doc in documents:
            citation = {
                "source": doc.metadata.get("source", "unknown"),
                "page": doc.metadata.get("page", 0) + 1,  # 1-indexed for display
                "filename": doc.metadata.get("filename", ""),
                "snippet": doc.page_content[:rag_config.SNIPPET_LENGTH] + "..."
            }
            citations.append(citation)
        
        return citations


class MultiCollectionRetriever:
    """
    Retriever that queries multiple per-file collections.
    
    This is the key component for querying across per-file collections
    while supporting file selection for targeted queries.
    """
    
    def __init__(
        self,
        collection_manager: 'PerFileCollectionManager',
        llm_provider: Optional[Any] = None,
        search_type: Optional[str] = None,
        k: Optional[int] = None,
        fetch_k: Optional[int] = None,
        lambda_mult: Optional[float] = None
    ):
        """
        Initialize multi-collection retriever.
        
        Args:
            collection_manager: PerFileCollectionManager instance
            llm_provider: LLM provider for potential re-ranking
            search_type: "mmr" or "similarity"
            k: Number of documents to retrieve per collection
            fetch_k: Documents to fetch before MMR
            lambda_mult: MMR diversity parameter
        """
        self.collection_manager = collection_manager
        self.llm_provider = llm_provider
        self.search_type = search_type or rag_config.SEARCH_TYPE
        self.k = k or rag_config.RETRIEVER_K
        self.fetch_k = fetch_k or rag_config.RETRIEVER_FETCH_K
        self.lambda_mult = lambda_mult or rag_config.RETRIEVER_LAMBDA_MULT
        
        # Target file hashes to query (empty = query all)
        self._target_file_hashes: List[str] = []
    
    def set_target_files(self, file_hashes: List[str]):
        """
        Set which files to query.
        
        Args:
            file_hashes: List of file hashes to query (empty = query all)
        """
        self._target_file_hashes = file_hashes
        logger.info(f"Set target files for query: {len(file_hashes)} files")
    
    def clear_target_files(self):
        """Clear file selection (will query all files)."""
        self._target_file_hashes = []
    
    def get_target_file_hashes(self) -> List[str]:
        """
        Get the list of file hashes to query.
        
        If no specific files are selected, returns all indexed file hashes.
        """
        if self._target_file_hashes:
            return self._target_file_hashes
        
        # Return all indexed files
        return [meta.file_hash for meta in self.collection_manager.registry.get_all()]
    
    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        search_type: Optional[str] = None
    ) -> List[Document]:
        """
        Retrieve relevant documents from target collections.
        
        Args:
            query: Search query
            k: Number of documents to retrieve per collection
            search_type: Search type to use
            
        Returns:
            List of relevant Document objects from all target collections
        """
        k = k or self.k
        search_type = search_type or self.search_type
        
        target_hashes = self.get_target_file_hashes()
        
        if not target_hashes:
            logger.warning("No files to query - index is empty")
            return []
        
        logger.info(f"Retrieving from {len(target_hashes)} collections, k={k}")
        
        all_documents = []
        
        for file_hash in target_hashes:
            try:
                docs = self.collection_manager.query_collection(
                    file_hash=file_hash,
                    query=query,
                    k=k
                )
                all_documents.extend(docs)
                logger.debug(f"Retrieved {len(docs)} docs from collection for {file_hash[:8]}")
            except Exception as e:
                logger.warning(f"Error querying collection for {file_hash}: {e}")
        
        logger.info(f"Total retrieved: {len(all_documents)} documents from {len(target_hashes)} collections")
        
        # Log retrieved documents if debug enabled
        if rag_config.ENABLE_DEBUG_LOGGING and all_documents:
            self._log_retrieved_documents(all_documents[:10])
        
        return all_documents
    
    def invoke(self, query: str) -> List[Document]:
        """
        Langchain-compatible invoke method.
        
        Args:
            query: Search query
            
        Returns:
            List of relevant Document objects
        """
        return self.retrieve(query)
    
    def _log_retrieved_documents(self, documents: List[Document]):
        """Log retrieved documents for debugging."""
        logger.info("=" * 60)
        logger.info("RETRIEVED DOCUMENTS (Multi-Collection):")
        logger.info("=" * 60)
        
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source", "unknown")
            page = doc.metadata.get("page", "?")
            file_hash = doc.metadata.get("file_hash", "?")[:8]
            snippet = doc.page_content[:rag_config.SNIPPET_LENGTH]
            
            logger.info(f"\n[{i+1}] Source: {source}, Page: {page}, Hash: {file_hash}")
            logger.info(f"    Snippet: {snippet}...")
        
        logger.info("=" * 60)
    
    def format_context(self, documents: List[Document]) -> str:
        """Format retrieved documents into a context string."""
        if not documents:
            return ""
        
        context_parts = []
        for i, doc in enumerate(documents):
            source = doc.metadata.get("source", "unknown")
            page = doc.metadata.get("page", "?")
            
            context_parts.append(
                f"[Document {i+1}] (Source: {source}, Page: {page})\n{doc.page_content}"
            )
        
        return "\n\n---\n\n".join(context_parts)
    
    def extract_citations(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """Extract citation information from documents."""
        citations = []
        
        for doc in documents:
            citation = {
                "source": doc.metadata.get("source", "unknown"),
                "page": doc.metadata.get("page", 0) + 1,
                "filename": doc.metadata.get("filename", ""),
                "file_hash": doc.metadata.get("file_hash", ""),
                "snippet": doc.page_content[:rag_config.SNIPPET_LENGTH] + "..."
            }
            citations.append(citation)
        
        return citations