"""
Configuration settings for FastAPI backend
"""
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import List, Optional
from enum import Enum


class LLMProviderType(str, Enum):
    OLLAMA = "ollama"
    GROQ = "groq"


class Settings(BaseSettings):
    """Application settings using pydantic-settings"""
    
    # Server settings
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    DEBUG: bool = True
    
    # CORS settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ]
    
    # Project paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    LOGS_DIR: Path = PROJECT_ROOT / "logs"
    EXPORTS_DIR: Path = PROJECT_ROOT / "exports"
    CONFIG_DIR: Path = PROJECT_ROOT / "config"
    MODELS_DIR: Path = PROJECT_ROOT / "models"
    
    # ==========================================================================
    # LLM Provider Configuration
    # ==========================================================================
    LLM_PROVIDER: str = "ollama"  # "ollama" or "groq"
    
    # Ollama settings (local LLM)
    OLLAMA_MODEL: str = "llama3.1:latest"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TEMPERATURE: float = 0.3
    
    # Groq Cloud settings
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_FALLBACK_TO_OLLAMA: bool = True
    
    # Groq available models
    GROQ_AVAILABLE_MODELS: List[str] = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
        "mixtral-8x7b-32768",
    ]
    
    # Ollama available models
    OLLAMA_AVAILABLE_MODELS: List[str] = [
        "llama3.1:latest",
        "phi3:latest",
        "mistral:latest",
        "gemma2:latest",
    ]
    
    # AI Model settings (computed from provider)
    MAX_ITERATIONS: int = 10
    TEMPERATURE: float = 0.3
    
    @property
    def DEFAULT_MODEL(self) -> str:
        if self.LLM_PROVIDER == LLMProviderType.GROQ:
            return self.GROQ_MODEL
        return self.OLLAMA_MODEL
    
    @property
    def AVAILABLE_MODELS(self) -> List[str]:
        if self.LLM_PROVIDER == LLMProviderType.GROQ:
            return self.GROQ_AVAILABLE_MODELS
        return self.OLLAMA_AVAILABLE_MODELS
    
    # Email settings (set via .env — NEVER hardcode credentials)
    EMAIL_RECEIVER: str = ""
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    
    # Database settings (SQL Server — legacy, set via .env if needed)
    SQL_SERVER_CONN_STR: str = ""
    
    # UI Configuration (for Gradio if needed in future)
    UI_PORT: int = 7860
    UI_HOST: str = "127.0.0.1"
    SHARE_GRADIO: bool = True
    
    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()

# Ensure directories exist
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

