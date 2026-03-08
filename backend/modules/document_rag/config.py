"""
Document RAG Configuration
==========================
Configuration settings for the Document RAG module.
All settings can be overridden via environment variables.

Supports multiple LLM providers:
- Ollama (local inference)
- Groq Cloud (OpenAI-compatible API)
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
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DEVICE: str = "cpu"  # Will be auto-detected
    NORMALIZE_EMBEDDINGS: bool = True
    
    # ===== Vector Store Settings =====
    PERSIST_DIRECTORY: str = "./data/chroma/document_rag"
    COLLECTION_NAME: str = "document_rag_collection"
    
    # ===== Retriever Settings =====
    RETRIEVER_K: int = 6
    RETRIEVER_FETCH_K: int = 20
    RETRIEVER_LAMBDA_MULT: float = 0.7
    SEARCH_TYPE: str = "mmr"  # "mmr" or "similarity"
    
    # ===== LLM Provider Settings =====
    LLM_PROVIDER: str = "ollama"  # "ollama" (dev only) or "groq" (production)
    
    # ===== Ollama LLM Settings (Development only) =====
    OLLAMA_MODEL: str = "llama3.1:latest"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TEMPERATURE: float = 0.3
    OLLAMA_TOP_P: float = 0.9
    OLLAMA_NUM_CTX: int = 4096
    
    # ===== Groq Cloud Settings =====
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_FALLBACK_TO_OLLAMA: bool = False  # Must be False in production
    
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
        
        # Vector Store
        self.PERSIST_DIRECTORY = os.getenv("RAG_PERSIST_DIRECTORY", self.PERSIST_DIRECTORY)
        self.COLLECTION_NAME = os.getenv("RAG_COLLECTION_NAME", self.COLLECTION_NAME)
        
        # Retriever
        self.RETRIEVER_K = int(os.getenv("RAG_RETRIEVER_K", self.RETRIEVER_K))
        self.SEARCH_TYPE = os.getenv("RAG_SEARCH_TYPE", self.SEARCH_TYPE)
        
        # LLM Provider
        self.LLM_PROVIDER = os.getenv("LLM_PROVIDER", self.LLM_PROVIDER).lower()
        
        # Ollama
        self.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", self.OLLAMA_MODEL)
        self.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", self.OLLAMA_BASE_URL)
        self.OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", self.OLLAMA_TEMPERATURE))
        
        # Groq Cloud
        self.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        self.GROQ_MODEL = os.getenv("GROQ_MODEL", self.GROQ_MODEL)
        self.GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", self.GROQ_BASE_URL)
        self.GROQ_FALLBACK_TO_OLLAMA = os.getenv(
            "GROQ_FALLBACK_TO_OLLAMA", "false"
        ).lower() == "true"
        
        # Production guard: reject Ollama provider
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment in ("staging", "production") and self.LLM_PROVIDER == "ollama":
            self.LLM_PROVIDER = "groq"  # Force Groq in production
        
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
