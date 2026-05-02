"""
Document RAG Configuration
==========================
Configuration settings for the Document RAG module.
All settings can be overridden via environment variables.

Uses Groq Cloud as the LLM provider.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, rely on system env vars


@dataclass
class RAGConfig:
    """Configuration for Document RAG module"""
    
    # ===== Chunking Settings =====
    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    CHUNK_SEPARATORS: List[str] = field(default_factory=lambda: [
        "\n\n", "\n", ".", "!", "?", ",", " ", ""
    ])
    
    # ===== Embedding Settings =====
    # Phase 2: switched from BAAI/bge-m3 (568 M params, 1024-dim, ~900 ms/chunk
    # on CPU) to multilingual-e5-small (118 M params, 384-dim, ~80-120 ms/chunk).
    # Trade-off accepted: smaller model, lower peak quality on hard cross-lingual
    # cases, ~10x faster indexing, ~3x lower RAM. E5 family REQUIRES the
    # "passage: " / "query: " prefixes which are applied automatically by
    # ``E5PrefixedEmbeddings`` in ``embeddings.py``.
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-small"
    EMBEDDING_DEVICE: str = "cpu"  # Will be auto-detected
    NORMALIZE_EMBEDDINGS: bool = True
    # Batch size used by sentence-transformers when encoding chunks. With
    # the small e5 model (Phase 2), batch=64 better utilizes CPU SIMD and
    # roughly halves embed_chunks time vs the library default of 32, with
    # only a transient RAM bump (~150-200 MB). Tunable via
    # ``RAG_EMBEDDING_BATCH_SIZE``; try 128 if RAM headroom allows.
    EMBEDDING_BATCH_SIZE: int = 64
    
    # ===== Vector Store Settings =====
    PERSIST_DIRECTORY: str = "./data/chroma/document_rag"
    COLLECTION_NAME: str = "document_rag_collection"
    
    # ===== Retriever Settings =====
    RETRIEVER_K: int = 6
    RETRIEVER_FETCH_K: int = 20
    RETRIEVER_LAMBDA_MULT: float = 0.7
    SEARCH_TYPE: str = "mmr"  # "mmr" or "similarity"
    
    # ===== LLM Provider Settings =====
    LLM_PROVIDER: str = "groq"
    
    # ===== Groq Cloud Settings =====
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_TEMPERATURE: float = 0.3
    
    # ===== Logging Settings =====
    ENABLE_DEBUG_LOGGING: bool = True
    SNIPPET_LENGTH: int = 200  # Characters to show in debug logs
    
    def __post_init__(self):
        """Load settings from environment variables"""
        # Chunking
        self.CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", self.CHUNK_SIZE))
        self.CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", self.CHUNK_OVERLAP))
        
        # Embedding
        self.EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", self.EMBEDDING_MODEL)
        self.EMBEDDING_DEVICE = os.getenv("RAG_EMBEDDING_DEVICE", self.EMBEDDING_DEVICE)
        try:
            self.EMBEDDING_BATCH_SIZE = int(
                os.getenv("RAG_EMBEDDING_BATCH_SIZE", self.EMBEDDING_BATCH_SIZE)
            )
        except (TypeError, ValueError):
            pass
        
        # Vector Store
        self.PERSIST_DIRECTORY = os.getenv("RAG_PERSIST_DIRECTORY", self.PERSIST_DIRECTORY)
        self.COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", self.COLLECTION_NAME)
        
        # Retriever
        self.RETRIEVER_K = int(os.getenv("RAG_RETRIEVER_K", self.RETRIEVER_K))
        self.SEARCH_TYPE = os.getenv("RAG_SEARCH_TYPE", self.SEARCH_TYPE)
        
        # LLM Provider
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", self.LLM_PROVIDER).lower()
        
        # Groq Cloud
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        self.GROQ_MODEL = os.getenv("GROQ_MODEL", self.GROQ_MODEL)
        self.GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", self.GROQ_BASE_URL)
        self.GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", self.GROQ_TEMPERATURE))
        
        # Logging
        self.ENABLE_DEBUG_LOGGING = os.getenv("RAG_DEBUG", "true").lower() == "true"
        
        # Auto-detect GPU
        self._detect_device()
        
        # Ensure persist directory exists
        Path(self.PERSIST_DIRECTORY).mkdir(parents=True, exist_ok=True)
    
    def _detect_device(self):
        """Auto-detect CUDA availability"""
        if self.EMBEDDING_DEVICE == "auto" or self.EMBEDDING_DEVICE == "cpu":
            try:
                import torch
                if torch.cuda.is_available():
                    self.EMBEDDING_DEVICE = "cuda"
                else:
                    self.EMBEDDING_DEVICE = "cpu"
            except ImportError:
                self.EMBEDDING_DEVICE = "cpu"


# Global config instance
rag_config = RAGConfig()
