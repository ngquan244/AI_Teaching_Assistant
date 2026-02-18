"""
Document RAG Module
===================
A completely independent RAG (Retrieval-Augmented Generation) module for document Q&A.

This module is SEPARATE from the existing chatbot/agent logic and provides:
- PDF document ingestion and chunking
- Vector storage with ChromaDB (persistent)
- Retrieval using embeddings
- Generation using configurable LLM backends (Ollama/Groq)
- Quiz generation from documents
- Runtime LLM provider switching

Usage:
    from backend.modules.document_rag import RAGService
    
    rag = RAGService()
    rag.ingest_document("path/to/document.pdf")
    result = rag.query("What is the main topic?")
    quiz = rag.generate_quiz("Topic", num_questions=5)
    
    # Switch LLM provider at runtime
    rag.set_llm_provider("groq")
"""

from .rag_service import RAGService
from .ingest import load_pdf_documents
from .chunking import chunk_documents
from .vectorstore import ChromaVectorStore
from .retriever import DocumentRetriever, MultiCollectionRetriever
from .rag_chain import RAGChain
from .quiz_generator import QuizGenerator
from .collection_manager import (
    PerFileCollectionManager,
    CollectionNameGenerator,
    CollectionRegistry,
    get_collection_manager,
    get_uploads_collection_manager,
    get_canvas_collection_manager,
)
from .llm_providers import (
    BaseLLM,
    OllamaLLM,
    GroqLLM,
    LLMFactory,
    LLMProvider,
)

__all__ = [
    "RAGService",
    "load_pdf_documents",
    "chunk_documents", 
    "ChromaVectorStore",
    "DocumentRetriever",
    "MultiCollectionRetriever",
    "RAGChain",
    "QuizGenerator",
    "PerFileCollectionManager",
    "CollectionNameGenerator",
    "CollectionRegistry",
    "get_collection_manager",
    "get_uploads_collection_manager",
    "get_canvas_collection_manager",
    "BaseLLM",
    "OllamaLLM",
    "GroqLLM",
    "LLMFactory",
    "LLMProvider",
]
