"""
Core application configuration with security-first design.
Loads all settings from environment variables.
"""
import warnings
from functools import lru_cache
from typing import List, Optional
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

# Development-only default keys (DO NOT USE IN PRODUCTION)
_DEV_JWT_SECRET = "dev-only-secret-key-change-in-production-min-32-chars"
_DEV_JWT_REFRESH_SECRET = "dev-only-refresh-secret-key-change-in-production-min-32"
_DEV_ENCRYPTION_KEY = "dev-only-encryption-key-32chars!"  # Must be 32 chars for Fernet


class Settings(BaseSettings):
    """
    Application settings using pydantic-settings.
    All sensitive values MUST come from environment variables in production.
    """
    
    # ==========================================================================
    # Server Configuration
    # ==========================================================================
    HOST: str = "0.0.0.0"  # Bind to all interfaces
    PORT: int = 8000  # Default port (8000 often conflicted with other services)
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production
    
    # ==========================================================================
    # CORS Configuration
    # ==========================================================================
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    
    # ==========================================================================
    # Database Configuration (PostgreSQL)
    # ==========================================================================
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "grader_user"
    POSTGRES_PASSWORD: str = "grader_secret_password"  # Same as docker-compose default
    POSTGRES_DB: str = "grader_db"
    
    # ==========================================================================
    # Redis & Celery Configuration
    # ==========================================================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    
    @property
    def REDIS_URL(self) -> str:
        """Redis connection URL."""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}"
    
    @property
    def CELERY_BROKER_URL(self) -> str:
        """Celery broker URL (Redis DB 0)."""
        return f"{self.REDIS_URL}/0"
    
    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        """Celery result backend URL (Redis DB 1)."""
        return f"{self.REDIS_URL}/1"
    
    # Rate limits
    LLM_RATE_LIMIT: str = "10/m"  # 10 requests per minute for LLM tasks
    CANVAS_RATE_LIMIT: str = "30/m"  # 30 requests per minute for Canvas API
    
    # Worker concurrency
    WORKER_CONCURRENCY_RAG: int = 4
    WORKER_CONCURRENCY_LLM: int = 2
    WORKER_CONCURRENCY_CANVAS: int = 2
    WORKER_CONCURRENCY_MISC: int = 4
    
    @property
    def DATABASE_URL(self) -> str:
        """Async PostgreSQL connection URL for FastAPI."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync PostgreSQL connection URL for Alembic migrations."""
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )
    
    # ==========================================================================
    # JWT Configuration
    # ==========================================================================
    JWT_SECRET_KEY: str = _DEV_JWT_SECRET  # Override in .env for production
    JWT_REFRESH_SECRET_KEY: str = _DEV_JWT_REFRESH_SECRET  # Separate key for refresh tokens
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes (short-lived)
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # ==========================================================================
    # Login Security Configuration
    # ==========================================================================
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS: int = 5  # Max login attempts per window
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300  # 5-minute window
    LOGIN_LOCKOUT_DURATION_SECONDS: int = 900  # 15-minute lockout after max attempts
    TOKEN_BLACKLIST_REDIS_DB: int = 2  # Redis DB for token blacklist
    
    # ==========================================================================
    # Encryption Configuration (for Canvas tokens)
    # ==========================================================================
    ENCRYPTION_KEY: str = _DEV_ENCRYPTION_KEY  # Override in .env for production
    
    # ==========================================================================
    # Password Hashing Configuration
    # ==========================================================================
    PASSWORD_HASH_ALGORITHM: str = "argon2"  # argon2 | bcrypt
    BCRYPT_ROUNDS: int = 12
    
    # ==========================================================================
    # Project Paths (computed from PROJECT_ROOT)
    # ==========================================================================
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    
    @property
    def DATA_DIR(self) -> Path:
        return self.PROJECT_ROOT / "data"
    
    @property
    def LOGS_DIR(self) -> Path:
        return self.PROJECT_ROOT / "logs"
    
    @property
    def EXPORTS_DIR(self) -> Path:
        return self.PROJECT_ROOT / "exports"
    
    @model_validator(mode='after')
    def warn_dev_secrets(self) -> 'Settings':
        """Warn if using development secrets in non-dev environment."""
        if self.ENVIRONMENT != "development":
            if self.JWT_SECRET_KEY == _DEV_JWT_SECRET:
                warnings.warn(
                    "Using development JWT_SECRET_KEY in non-development environment! "
                    "Set JWT_SECRET_KEY in your .env file.",
                    UserWarning
                )
            if self.JWT_REFRESH_SECRET_KEY == _DEV_JWT_REFRESH_SECRET:
                warnings.warn(
                    "Using development JWT_REFRESH_SECRET_KEY in non-development environment! "
                    "Set JWT_REFRESH_SECRET_KEY in your .env file.",
                    UserWarning
                )
            if self.ENCRYPTION_KEY == _DEV_ENCRYPTION_KEY:
                warnings.warn(
                    "Using development ENCRYPTION_KEY in non-development environment! "
                    "Set ENCRYPTION_KEY in your .env file.",
                    UserWarning
                )
        return self
    
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
    
    # AI Model settings
    MAX_ITERATIONS: int = 10
    TEMPERATURE: float = 0.3
    
    @property
    def DEFAULT_MODEL(self) -> str:
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_MODEL
        return self.OLLAMA_MODEL
    
    @property
    def AVAILABLE_MODELS(self) -> List[str]:
        if self.LLM_PROVIDER == "groq":
            return self.GROQ_AVAILABLE_MODELS
        return self.OLLAMA_AVAILABLE_MODELS
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Use dependency injection in FastAPI routes.
    """
    return Settings()


# Global settings instance
settings = get_settings()
