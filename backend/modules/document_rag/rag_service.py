"""
RAG Service Module
==================
Main service class that coordinates all RAG operations.
This is the primary interface for the Document RAG feature.

Supports multiple LLM providers:
- Ollama (local inference)
- Groq Cloud (OpenAI-compatible API)
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from langchain_core.documents import Document

from .config import rag_config
from .ingest import load_pdf_documents, get_file_metadata, compute_file_hash
from .chunking import chunk_documents
from .vectorstore import ChromaVectorStore
from .collection_manager import (
    PerFileCollectionManager,
    get_uploads_collection_manager,
    CollectionNameGenerator
)
from .retriever import DocumentRetriever, MultiCollectionRetriever
from .rag_chain import RAGChain
from .quiz_generator import QuizGenerator
from .topic_storage import topic_storage
from .llm_providers import BaseLLM, LLMFactory, LLMProvider

logger = logging.getLogger(__name__)


class RAGService:
    """
    Main service for Document RAG operations.
    
    Provides a simple API for:
    - Document ingestion (PDF upload and indexing)
    - Query execution (RAG-based Q&A)
    - Quiz generation
    - Index management (stats, reset)
    - Runtime LLM provider switching
    
    Usage:
        rag = RAGService()
        
        # Ingest a document
        result = rag.ingest_document("path/to/doc.pdf")
        
        # Query the knowledge base
        answer = rag.query("What is the main topic?")
        
        # Switch LLM provider at runtime
        rag.set_llm_provider("groq")
    """
    
    _instance: Optional["RAGService"] = None
    
    def __init__(
        self,
        persist_directory: Optional[str] = None,
        collection_name: Optional[str] = None,
        ollama_model: Optional[str] = None,
        llm_provider: Optional[str] = None
    ):
        """
        Initialize RAG Service.
        
        Args:
            persist_directory: Directory for vector store persistence
            collection_name: Name of the vector collection (deprecated, now per-file)
            ollama_model: Model to use for generation (legacy, for backwards compatibility)
            llm_provider: LLM provider to use ("ollama" or "groq")
        """
        self.persist_directory = persist_directory or rag_config.PERSIST_DIRECTORY
        self.collection_name = collection_name or rag_config.COLLECTION_NAME
        self.ollama_model = ollama_model or rag_config.OLLAMA_MODEL
        self._llm_provider_name = llm_provider or rag_config.LLM_PROVIDER
        
        logger.info("Initializing RAG Service with per-file collections...")
        logger.info(f"Persist directory: {self.persist_directory}")
        logger.info(f"LLM provider: {self._llm_provider_name}")
        
        # Per-file collection manager (replaces global vectorstore)
        self._collection_manager: Optional[PerFileCollectionManager] = None
        
        # Legacy support - will be deprecated
        self._vector_store: Optional[ChromaVectorStore] = None
        
        # Dynamically created per-file retrievers
        self._retrievers: Dict[str, DocumentRetriever] = {}
        self._multi_retriever: Optional[MultiCollectionRetriever] = None
        
        self._rag_chain: Optional[RAGChain] = None
        self._quiz_generator: Optional[QuizGenerator] = None
        self._llm_provider: Optional[BaseLLM] = None
        
        # Track currently selected files for querying
        self._selected_file_hashes: List[str] = []
        
        # Lazy initialization flag
        self._initialized = False
    
    def _ensure_initialized(self):
        """Ensure all components are initialized."""
        if self._initialized:
            return
        
        logger.info("Initializing RAG components with per-file collection manager...")
        
        # Initialize per-file collection manager (replaces global vectorstore)
        self._collection_manager = get_uploads_collection_manager()
        
        # Legacy vector store for backwards compatibility (will be deprecated)
        # Only used for reading from old global collection if it exists
        try:
            self._vector_store = ChromaVectorStore(
                persist_directory=self.persist_directory,
                collection_name=self.collection_name
            )
        except Exception as e:
            logger.warning(f"Could not initialize legacy vectorstore: {e}")
            self._vector_store = None
        
        # Initialize LLM provider using factory
        self._llm_provider = LLMFactory.create()
        
        # Initialize multi-collection retriever (queries across selected files)
        self._multi_retriever = MultiCollectionRetriever(
            collection_manager=self._collection_manager,
            llm_provider=self._llm_provider
        )
        
        # Initialize RAG chain with multi-collection retriever
        self._rag_chain = RAGChain(
            retriever=self._multi_retriever,
            llm_provider=self._llm_provider
        )
        
        # Initialize Quiz Generator with multi-collection retriever
        self._quiz_generator = QuizGenerator(
            retriever=self._multi_retriever,
            llm_provider=self._llm_provider
        )
        
        self._initialized = True
        logger.info(f"RAG Service initialized successfully with provider: {self._llm_provider.provider_name}")
    
    @classmethod
    def get_instance(cls) -> "RAGService":
        """Get singleton instance of RAG Service."""
        if cls._instance is None:
            cls._instance = RAGService()
        return cls._instance
    
    def ingest_document(
        self,
        file_path: str,
        skip_if_exists: bool = True,
        extract_topics: bool = True
    ) -> Dict[str, Any]:
        """
        Ingest a PDF document into the vector store.
        
        Args:
            file_path: Path to PDF file
            skip_if_exists: Skip if document already indexed
            extract_topics: Extract and save topics after indexing
            
        Returns:
            Dictionary with ingestion results
        """
        self._ensure_initialized()
        
        logger.info(f"Ingesting document into per-file collection: {file_path}")
        
        try:
            # Check if file exists
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
            
            # Check for duplicates using per-file collection manager
            if skip_if_exists and self._collection_manager.is_indexed(file_hash):
                logger.info(f"Document already indexed in per-file collection: {file_path}")
                collection_name = self._collection_manager.get_collection_name(file_hash)
                return {
                    "success": True,
                    "message": "Document already indexed",
                    "file_hash": file_hash,
                    "filename": filename,
                    "collection_name": collection_name,
                    "chunks_added": 0,
                    "already_indexed": True,
                    "has_topics": topic_storage.has_topics(file_hash)
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
            
            # Add to per-file collection (NOT global collection)
            # This is the key change that enables concurrent indexing
            added_count = self._collection_manager.add_documents(
                file_hash=file_hash,
                filename=filename,
                documents=chunks,
                course_id=None,  # Regular upload, not Canvas
                replace_existing=True  # Idempotent: re-indexing replaces old data
            )
            
            collection_name = self._collection_manager.get_collection_name(file_hash)
            logger.info(f"Successfully ingested {added_count} chunks from {file_path} into collection: {collection_name}")
            
            # Extract and save topics for this document
            topics_extracted = []
            if extract_topics:
                try:
                    logger.info(f"Extracting topics for {filename}...")
                    topics_result = self._extract_topics_from_chunks(chunks, file_meta)
                    if topics_result.get("success") and topics_result.get("topics"):
                        topics_extracted = topics_result["topics"]
                        topic_storage.save_topics(
                            file_hash=file_hash,
                            filename=filename,
                            topics=topics_extracted
                        )
                        logger.info(f"Saved {len(topics_extracted)} topics for {filename}")
                except Exception as e:
                    logger.warning(f"Could not extract topics: {e}")
            
            return {
                "success": True,
                "message": "Document indexed successfully into per-file collection",
                "file_hash": file_hash,
                "filename": filename,
                "collection_name": collection_name,
                "pages_loaded": len(documents),
                "chunks_added": added_count,
                "already_indexed": False,
                "topics_extracted": len(topics_extracted)
            }
            
        except Exception as e:
            logger.error(f"Error ingesting document: {e}")
            return {
                "success": False,
                "error": str(e),
                "chunks_added": 0
            }
    
    def _extract_topics_from_chunks(
        self,
        chunks: List[Document],
        file_meta: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract topics from document chunks using LLM.
        
        Args:
            chunks: Document chunks
            file_meta: File metadata
            
        Returns:
            Dictionary with topics
        """
        # Get sample content from chunks (limit to avoid token overflow)
        sample_chunks = chunks[:15]
        context = "\n\n---\n\n".join([c.page_content for c in sample_chunks])
        
        return self._quiz_generator.extract_topics_from_context(
            context=context[:8000],
            max_topics=10
        )
    
    def query(
        self,
        question: str,
        k: Optional[int] = None,
        return_context: bool = False,
        file_hashes: Optional[List[str]] = None,
        selected_documents: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Query the document knowledge base.
        
        Args:
            question: User's question
            k: Number of documents to retrieve
            return_context: Include retrieved context in response
            file_hashes: Optional list of file hashes to query (per-file collections)
            selected_documents: Optional list of filenames to query
            
        Returns:
            Dictionary with:
            - answer: Generated answer
            - sources: List of source citations
            - context: (optional) Retrieved context
        """
        self._ensure_initialized()
        
        logger.info(f"Processing query: {question}")
        
        # Determine which collections to query
        target_hashes = file_hashes or []
        
        # If filenames provided, resolve to file hashes
        if selected_documents and not target_hashes:
            for meta in self._collection_manager.registry.get_all():
                if meta.filename in selected_documents:
                    target_hashes.append(meta.file_hash)
        
        # If no specific files selected, query all indexed files
        if not target_hashes:
            target_hashes = [meta.file_hash for meta in self._collection_manager.registry.get_all()]
        
        # Check if there are indexed documents
        if not target_hashes:
            return {
                "success": False,
                "answer": "Chưa có tài liệu nào được index. Vui lòng upload và build index trước.",
                "sources": [],
                "error": "No documents indexed"
            }
        
        logger.info(f"Querying {len(target_hashes)} collections")
        
        try:
            # Set the target file hashes for the multi-retriever
            self._multi_retriever.set_target_files(target_hashes)
            
            result = self._rag_chain.query(
                question=question,
                k=k,
                return_context=return_context
            )
            
            result["success"] = True
            result["collections_queried"] = len(target_hashes)
            return result
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return {
                "success": False,
                "answer": f"Lỗi khi xử lý câu hỏi: {str(e)}",
                "sources": [],
                "error": str(e)
            }
    
    def get_index_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the document index.
        
        Returns:
            Dictionary with index statistics (aggregated across all per-file collections)
        """
        self._ensure_initialized()
        
        # Get stats from per-file collection manager
        indexed_files = self._collection_manager.get_indexed_files()
        total_chunks = sum(f.get("chunk_count", 0) for f in indexed_files)
        
        return {
            "persist_directory": self.persist_directory,
            "collection_type": "per-file",
            "indexed_files_count": len(indexed_files),
            "total_documents": total_chunks,
            "indexed_files": indexed_files,
            "embedding_model": rag_config.EMBEDDING_MODEL
        }
    
    def reset_index(self) -> Dict[str, Any]:
        """
        Reset the document index (delete all per-file collections).
        
        Returns:
            Dictionary with reset status
        """
        self._ensure_initialized()
        
        logger.warning("Resetting all per-file document collections")
        
        try:
            # Reset all per-file collections
            success = self._collection_manager.reset_all()
            
            # Also clear stored topics
            topic_storage.clear()
            logger.info("Cleared stored topics")
            
            if success:
                return {
                    "success": True,
                    "message": "Index reset successfully"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to reset index"
                }
        except Exception as e:
            logger.error(f"Error resetting index: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def check_ollama_status(self) -> Dict[str, Any]:
        """
        Check LLM provider connection status.
        Kept for backwards compatibility - now checks current provider.
        
        Returns:
            Dictionary with provider status
        """
        self._ensure_initialized()
        
        return self._rag_chain.check_connection()
    
    def check_llm_status(self) -> Dict[str, Any]:
        """
        Check current LLM provider connection status.
        
        Returns:
            Dictionary with provider status
        """
        return self.check_ollama_status()
    
    def set_llm_provider(
        self,
        provider: str,
        model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Switch LLM provider at runtime.
        
        Args:
            provider: Provider name ("ollama" or "groq")
            model: Optional model name override
            
        Returns:
            Dictionary with switch status
        """
        logger.info(f"Switching LLM provider to: {provider}, model: {model}")
        
        # Use factory to set and validate provider
        result = LLMFactory.set_provider(provider, model)
        
        if not result.get("success"):
            return result
        
        # If already initialized, update components with new provider
        if self._initialized:
            try:
                # Create new LLM provider
                new_provider = LLMFactory.create(provider=provider, model=model)
                
                # Update all components
                self._llm_provider = new_provider
                self._rag_chain.set_llm_provider(new_provider)
                self._quiz_generator.set_llm_provider(new_provider)
                
                logger.info(f"LLM provider switched to: {provider}")
                
                # Test connection
                connection_status = new_provider.check_connection()
                
                return {
                    "success": True,
                    "provider": provider,
                    "model": model or new_provider.model,
                    "message": f"Successfully switched to {provider}",
                    "connection": connection_status
                }
                
            except Exception as e:
                logger.error(f"Error switching LLM provider: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "message": f"Failed to switch to {provider}: {str(e)}"
                }
        
        # Not initialized yet, just store the preference
        self._llm_provider_name = provider
        return result
    
    def get_llm_provider_info(self) -> Dict[str, Any]:
        """
        Get current LLM provider information.
        
        Returns:
            Dictionary with provider info
        """
        current = LLMFactory.get_current_provider()
        
        return {
            "success": True,
            "current_provider": current["provider"],
            "current_model": current["model"],
            "available_providers": current["available_providers"],
            "groq_configured": bool(rag_config.GROQ_API_KEY),
            "ollama_base_url": rag_config.OLLAMA_BASE_URL
        }
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get current RAG configuration.
        
        Returns:
            Dictionary with configuration values
        """
        llm_info = LLMFactory.get_current_provider()
        
        return {
            "persist_directory": self.persist_directory,
            "collection_name": self.collection_name,
            "llm_provider": llm_info["provider"],
            "llm_model": llm_info["model"],
            "available_providers": llm_info["available_providers"],
            "ollama_model": rag_config.OLLAMA_MODEL,
            "ollama_base_url": rag_config.OLLAMA_BASE_URL,
            "groq_model": rag_config.GROQ_MODEL,
            "groq_configured": bool(rag_config.GROQ_API_KEY),
            "chunk_size": rag_config.CHUNK_SIZE,
            "chunk_overlap": rag_config.CHUNK_OVERLAP,
            "embedding_model": rag_config.EMBEDDING_MODEL,
            "retriever_k": rag_config.RETRIEVER_K,
            "search_type": rag_config.SEARCH_TYPE
        }
    
    def generate_quiz(
        self,
        topic: str = None,
        topics: List[str] = None,
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "vi",
        k: int = 10,
        selected_documents: List[str] = None
    ) -> Dict[str, Any]:
        """
        Generate quiz questions from the document knowledge base.
        
        Supports both single topic (legacy) and multiple topics.
        
        Args:
            topic: Single topic or description (legacy support)
            topics: List of topics for quiz generation (new)
            num_questions: Number of questions to generate (1-30)
            difficulty: Difficulty level - "easy", "medium", or "hard"
            language: "vi" for Vietnamese, "en" for English
            k: Number of documents to retrieve for context per topic
            selected_documents: Optional list of document filenames to retrieve from
            
        Returns:
            Dictionary with:
            - success: Whether generation succeeded
            - questions: List of quiz questions
            - error: Error message if any
        """
        self._ensure_initialized()
        
        # Handle both single topic and multiple topics
        if topics and len(topics) > 0:
            topic_list = topics
        elif topic:
            topic_list = [topic]
        else:
            return {
                "success": False,
                "questions": [],
                "error": "Cần có ít nhất một chủ đề để tạo quiz"
            }
        
        logger.info(f"Generating quiz: topics={topic_list}, num_questions={num_questions}, difficulty={difficulty}")
        
        # Validate num_questions
        num_questions = max(1, min(30, num_questions))
        
        # Check if index has documents
        stats = self.get_index_stats()
        if stats["total_documents"] == 0:
            return {
                "success": False,
                "questions": [],
                "error": "Chưa có tài liệu nào được index. Vui lòng upload và build index trước."
            }
        
        try:
            # If multiple topics, use the new multi-topic method
            if len(topic_list) > 1:
                result = self._quiz_generator.generate_quiz_multi_topics(
                    topics=topic_list,
                    num_questions=num_questions,
                    difficulty=difficulty,
                    language=language,
                    k=k
                )
            else:
                # Single topic - use existing method
                result = self._quiz_generator.generate_quiz(
                    topic=topic_list[0],
                    num_questions=num_questions,
                    difficulty=difficulty,
                    language=language,
                    k=k
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating quiz: {e}")
            return {
                "success": False,
                "questions": [],
                "error": f"Lỗi khi tạo quiz: {str(e)}"
            }
    
    def extract_topics(self, max_topics: int = 10) -> Dict[str, Any]:
        """
        Extract suggested topics from indexed documents (legacy method).
        This calls LLM to extract topics dynamically.
        
        Args:
            max_topics: Maximum number of topics to extract
            
        Returns:
            Dictionary with topics
        """
        self._ensure_initialized()
        
        logger.info("Extracting topics from indexed documents")
        
        stats = self.get_index_stats()
        if stats["total_documents"] == 0:
            return {
                "success": False,
                "topics": [],
                "message": "Chưa có tài liệu nào được index"
            }
        
        try:
            result = self._quiz_generator.extract_topics(max_topics=max_topics)
            return result
            
        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return {
                "success": False,
                "topics": [],
                "message": f"Lỗi: {str(e)}"
            }
    
    def get_document_topics(self, filename: str) -> Dict[str, Any]:
        """
        Get pre-extracted topics for a specific document.
        No LLM call needed - returns cached topics from indexing.
        
        Args:
            filename: Document filename
            
        Returns:
            Dictionary with topics for the document
        """
        logger.info(f"Getting topics for document: {filename}")
        
        topics = topic_storage.get_topics_by_filename(filename)
        
        if topics is not None:
            return {
                "success": True,
                "topics": topics,
                "filename": filename,
                "cached": True
            }
        
        # Topics not found - try to extract them now
        logger.info(f"No cached topics, extracting for: {filename}")
        result = self.extract_topics_for_document(filename)
        
        if result.get("success"):
            return result
        
        return {
            "success": False,
            "topics": [],
            "filename": filename,
            "message": "Không tìm thấy topics cho tài liệu này. Có thể cần index lại."
        }
    
    def extract_topics_for_document(self, filename: str) -> Dict[str, Any]:
        """
        Extract and cache topics for a specific document.
        
        Args:
            filename: Document filename
            
        Returns:
            Dictionary with extracted topics
        """
        self._ensure_initialized()
        
        logger.info(f"Extracting topics for document: {filename}")
        
        try:
            # Find the file_hash for this filename from collection registry
            indexed_files = self._collection_manager.get_indexed_files()
            file_hash = None
            for file_info in indexed_files:
                if file_info.get("filename") == filename:
                    file_hash = file_info.get("file_hash")
                    break
            
            if not file_hash:
                return {
                    "success": False,
                    "topics": [],
                    "filename": filename,
                    "message": "Tài liệu chưa được index"
                }
            
            # Get document content from per-file collection manager (specific file)
            all_docs = self._collection_manager.get_all_document_content(
                file_hash=file_hash,
                max_docs=50
            )
            
            if not all_docs:
                return {
                    "success": False,
                    "topics": [],
                    "filename": filename,
                    "message": "Không tìm thấy nội dung tài liệu"
                }
            
            # Use content as context
            context = "\n\n---\n\n".join(all_docs[:15])
            
            # Extract topics using LLM
            result = self._quiz_generator.extract_topics_from_context(
                context=context[:8000],
                max_topics=10
            )
            
            if result.get("success") and result.get("topics"):
                topics = result["topics"]
                
                # Save to storage using the actual file_hash from the collection registry
                topic_storage.save_topics(
                    file_hash=file_hash,
                    filename=filename,
                    topics=topics
                )
                
                return {
                    "success": True,
                    "topics": topics,
                    "filename": filename,
                    "cached": False,
                    "just_extracted": True
                }
            
            return {
                "success": False,
                "topics": [],
                "filename": filename,
                "message": "Không thể trích xuất topics"
            }
            
        except Exception as e:
            logger.error(f"Error extracting topics for {filename}: {e}")
            return {
                "success": False,
                "topics": [],
                "filename": filename,
                "message": str(e)
            }
    
    def get_indexed_documents_with_topics(self) -> Dict[str, Any]:
        """
        Get list of all indexed documents with their topic counts.
        Returns documents from topic_storage and also from indexed files.
        
        Returns:
            Dictionary with document list
        """
        self._ensure_initialized()
        
        # Get documents that already have topics
        docs_with_topics = topic_storage.get_all_documents()
        docs_dict = {d["filename"]: d for d in docs_with_topics}
        
        # Get indexed files from per-file collection manager (not legacy vectorstore)
        indexed_files = self._collection_manager.get_indexed_files()
        
        # Merge: add files that don't have topics yet
        for file_info in indexed_files:
            filename = file_info.get("filename", "unknown")
            if filename not in docs_dict:
                docs_dict[filename] = {
                    "filename": filename,
                    "topic_count": 0,  # Not extracted yet
                    "extracted_at": None
                }
        
        documents = list(docs_dict.values())
        
        return {
            "success": True,
            "documents": documents,
            "count": len(documents)
        }
    
    def update_document_topics(self, filename: str, topics: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Update topics for a specific document.
        
        Args:
            filename: Document filename
            topics: List of topic dictionaries with 'name' and optionally 'description'
            
        Returns:
            Dictionary with success status
        """
        logger.info(f"Updating topics for document: {filename}, topics: {topics}")
        
        success = topic_storage.update_topics_by_filename(filename, topics)
        
        if success:
            return {
                "success": True,
                "filename": filename,
                "topics": topics,
                "count": len(topics),
                "message": f"Đã cập nhật {len(topics)} chủ đề"
            }
        else:
            return {
                "success": False,
                "filename": filename,
                "message": "Không tìm thấy tài liệu"
            }
