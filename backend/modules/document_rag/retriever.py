"""
Document Retriever Module
=========================
Retrieval functionality for the Document RAG system.
Includes both single-collection and multi-collection retrievers.
"""

import logging
from collections import defaultdict
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from langchain_core.documents import Document

from .config import rag_config
from .vectorstore import ChromaVectorStore
from backend.core.logger import quiz_logger

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
    
    def resolve_target_file_hashes(
        self,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> List[str]:
        """
        Resolve which file hashes to query.
        
        Args:
            target_file_hashes: Explicit list of file hashes (takes priority)
            user_id: If given and no target_file_hashes, return all files for this user
            
        Returns:
            List of file hashes to query
        """
        if target_file_hashes is not None:
            return target_file_hashes
        
        # Return all indexed files for the user
        return [meta.file_hash for meta in self.collection_manager.registry.get_all(user_id=user_id)]
    
    def retrieve(
        self,
        query: str,
        k: Optional[int] = None,
        search_type: Optional[str] = None,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Retrieve relevant documents from target collections.
        
        Args:
            query: Search query
            k: Number of documents to retrieve per collection
            search_type: Search type to use
            target_file_hashes: Explicit list of file hashes to query
            user_id: User ID to scope the query (used when target_file_hashes is empty)
            
        Returns:
            List of relevant Document objects from all target collections
        """
        k = k or self.k
        search_type = search_type or self.search_type
        
        # Reload registry from disk to pick up cross-process changes.
        # In multi-process Docker, the backend may have ingested/deleted
        # collections since this worker started. Without reload, hash_to_name
        # will be empty and query_collection will use wrong collection names.
        self.collection_manager.registry.reload()
        
        resolved_hashes = self.resolve_target_file_hashes(target_file_hashes, user_id)
        
        if not resolved_hashes:
            logger.warning("No files to query - index is empty")
            return []
        
        # Map hashes to filenames for debug — detail to file
        # Try user-scoped first, fall back to all entries (canvas has user_id=null)
        hash_to_name = {}
        for meta in self.collection_manager.registry.get_all(user_id=user_id):
            hash_to_name[meta.file_hash] = meta.filename
        if not hash_to_name:
            for meta in self.collection_manager.registry.get_all():
                hash_to_name[meta.file_hash] = meta.filename
        hash_info = [(h[:8], hash_to_name.get(h, '?')) for h in resolved_hashes]
        quiz_logger.info(f"Retrieving from {len(resolved_hashes)} collections: {hash_info}, k={k}, target_file_hashes_was={'None' if target_file_hashes is None else f'list[{len(target_file_hashes)}]'}")
        
        all_documents = []
        
        for file_hash in resolved_hashes:
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
        
        logger.info(f"Total retrieved: {len(all_documents)} documents from {len(resolved_hashes)} collections")
        
        # Log retrieved documents if debug enabled
        if rag_config.ENABLE_DEBUG_LOGGING and all_documents:
            self._log_retrieved_documents(all_documents[:10])
        
        return all_documents

    def retrieve_with_budget(
        self,
        query: str,
        max_total_docs: int,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        round_one_cap: int = 2,
        round_n_cap: int = 1,
    ) -> List[Document]:
        """
        Retrieve documents with a global budget instead of a fixed per-collection k.

        Strategy:
        - Single collection: allow that collection to use the whole budget.
        - Multiple collections: fetch a per-collection candidate pool, then allocate
          results using a round-based soft cap (2 docs in round 1, then 1 doc/round).
        """
        max_total_docs = max(1, max_total_docs)

        self.collection_manager.registry.reload()
        resolved_hashes = self.resolve_target_file_hashes(target_file_hashes, user_id)

        if not resolved_hashes:
            logger.warning("No files to query - index is empty")
            return []

        if len(resolved_hashes) == 1:
            file_hash = resolved_hashes[0]
            docs = self.collection_manager.query_collection(
                file_hash=file_hash,
                query=query,
                k=max_total_docs,
            )
            logger.info(
                "Budgeted retrieval (single collection): requested=%s returned=%s",
                max_total_docs,
                len(docs),
            )
            return docs[:max_total_docs]

        fetch_per_collection = min(
            max_total_docs,
            max(6, (max_total_docs // max(1, min(len(resolved_hashes), 6))) + 4),
        )

        per_collection_docs: Dict[str, List[Document]] = {}
        for file_hash in resolved_hashes:
            try:
                docs = self.collection_manager.query_collection(
                    file_hash=file_hash,
                    query=query,
                    k=fetch_per_collection,
                )
                per_collection_docs[file_hash] = docs
            except Exception as e:
                logger.warning(f"Error querying collection for {file_hash}: {e}")
                per_collection_docs[file_hash] = []

        selected = self._round_robin_allocate(
            per_collection_docs=per_collection_docs,
            max_total_docs=max_total_docs,
            round_one_cap=round_one_cap,
            round_n_cap=round_n_cap,
        )

        logger.info(
            "Budgeted retrieval (multi collection): budget=%s selected=%s sources=%s",
            max_total_docs,
            len(selected),
            len([docs for docs in per_collection_docs.values() if docs]),
        )
        return selected

    def _round_robin_allocate(
        self,
        per_collection_docs: Dict[str, List[Document]],
        max_total_docs: int,
        round_one_cap: int = 2,
        round_n_cap: int = 1,
    ) -> List[Document]:
        """Allocate a global budget across collections with soft round-based caps."""
        selected: List[Document] = []
        consumed: Dict[str, int] = defaultdict(int)
        order = [file_hash for file_hash, docs in per_collection_docs.items() if docs]

        if not order:
            return []

        round_index = 0
        while len(selected) < max_total_docs:
            made_progress = False
            cap = round_one_cap if round_index == 0 else round_n_cap

            for file_hash in order:
                docs = per_collection_docs[file_hash]
                start = consumed[file_hash]
                end = min(start + cap, len(docs))
                if start >= end:
                    continue

                slice_docs = docs[start:end]
                selected.extend(slice_docs)
                consumed[file_hash] = end
                made_progress = True

                if len(selected) >= max_total_docs:
                    return selected[:max_total_docs]

            if not made_progress:
                break
            round_index += 1

        return selected[:max_total_docs]
    
    def invoke(
        self,
        query: str,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> List[Document]:
        """
        Langchain-compatible invoke method.
        
        Args:
            query: Search query
            target_file_hashes: Explicit list of file hashes to query
            user_id: User ID to scope the query
            
        Returns:
            List of relevant Document objects
        """
        return self.retrieve(query, target_file_hashes=target_file_hashes, user_id=user_id)
    
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
