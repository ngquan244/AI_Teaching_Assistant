"""
Core application configuration — single source of truth.
Loads all settings from environment variables.
"""
import warnings
from enum import Enum
from functools import lru_cache
from typing import List, Optional
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings


# =============================================================================
# Enums
# =============================================================================

class LLMProviderType(str, Enum):
    """Supported LLM providers."""
    OLLAMA = "ollama"
    GROQ = "groq"


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
    PORT: int = 8000
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
        "http://localhost:5175",
        "http://127.0.0.1:5175",
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
    # Database Configuration (SQL Server — legacy, set via .env)
    # ==========================================================================
    SQL_SERVER_CONN_STR: str = ""
    
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
    
    # Celery eager mode (run tasks synchronously — no Redis/workers needed)
    CELERY_TASK_ALWAYS_EAGER: bool = False
    
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
    # Signup Configuration
    # ==========================================================================
    SIGNUP_MODE: str = "open"  # "open" | "invite" | "closed"
    SIGNUP_INVITE_CODE: str = ""  # Fallback env-var code (min 16 chars)
    INVITE_SECRET: str = ""  # HMAC key for hashing DB invite codes (min 32 chars)

    # Signup rate-limit: same structure as login
    SIGNUP_RATE_LIMIT_MAX_ATTEMPTS: int = 5
    SIGNUP_RATE_LIMIT_WINDOW_SECONDS: int = 600  # 10-minute window
    SIGNUP_LOCKOUT_DURATION_SECONDS: int = 1800  # 30-minute lockout

    @field_validator("SIGNUP_MODE")
    @classmethod
    def validate_signup_mode(cls, v: str) -> str:
        allowed = {"open", "invite", "closed"}
        if v not in allowed:
            raise ValueError(f"SIGNUP_MODE must be one of {allowed}, got '{v}'")
        return v
    
    # ==========================================================================
    # Password Hashing Configuration
    # ==========================================================================
    PASSWORD_HASH_ALGORITHM: str = "argon2"  # argon2 | bcrypt
    BCRYPT_ROUNDS: int = 12
    
    # ==========================================================================
    # Email / SMTP Configuration (set via .env — NEVER hardcode credentials)
    # ==========================================================================
    EMAIL_RECEIVER: str = ""
    EMAIL_USER: str = ""     # SMTP login username (e.g. Gmail address)
    EMAIL_PASSWORD: str = ""  # SMTP login password (e.g. Google App Password)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465      # SSL port; use 587 for STARTTLS
    
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
    
    @property
    def CONFIG_DIR(self) -> Path:
        return self.PROJECT_ROOT / "config"
    
    @property
    def MODELS_DIR(self) -> Path:
        return self.PROJECT_ROOT / "models"
    
    @property
    def USER_WORKSPACES_DIR(self) -> Path:
        return self.DATA_DIR / "user_workspaces"
    
    @property
    def GUIDE_IMAGES_DIR(self) -> Path:
        return self.DATA_DIR / "guide_images"
    
    def get_user_filled_dir(self, user_id: str) -> Path:
        """Get per-user directory for uploaded exam images."""
        return self.USER_WORKSPACES_DIR / user_id / "filled"
    
    def get_user_results_dir(self, user_id: str) -> Path:
        """Get per-user directory for grading results."""
        return self.USER_WORKSPACES_DIR / user_id / "results"
    
    def get_user_result_file(self, user_id: str) -> Path:
        """Get per-user grading result JSON file path."""
        return self.get_user_results_dir(user_id) / "result.json"

    def get_user_rag_upload_dir(self, user_id: str) -> Path:
        """Get per-user directory for RAG document uploads."""
        return self.DATA_DIR / "rag_uploads" / user_id

    def get_user_canvas_rag_dir(self, user_id: str) -> Path:
        """Get per-user directory for Canvas RAG file downloads."""
        return self.DATA_DIR / "canvas_rag_uploads" / user_id
    
    @model_validator(mode='after')
    def validate_secrets(self) -> 'Settings':
        """
        Enforce production secrets.
        - development: warn only (local dev keeps working).
        - staging / production: raise ValueError → app refuses to start.
        """
        _dev_secrets = {
            "JWT_SECRET_KEY": (self.JWT_SECRET_KEY, _DEV_JWT_SECRET),
            "JWT_REFRESH_SECRET_KEY": (self.JWT_REFRESH_SECRET_KEY, _DEV_JWT_REFRESH_SECRET),
            "ENCRYPTION_KEY": (self.ENCRYPTION_KEY, _DEV_ENCRYPTION_KEY),
        }
        _default_db_password = "grader_secret_password"

        if self.ENVIRONMENT == "development":
            # Soft warnings — local dev keeps working
            for name, (current, dev_default) in _dev_secrets.items():
                if current == dev_default:
                    warnings.warn(
                        f"Using development {name} — set {name} in .env before deploying.",
                        UserWarning,
                    )
        else:
            # Hard fail — production / staging must not use dev defaults
            insecure: list[str] = []
            for name, (current, dev_default) in _dev_secrets.items():
                if current == dev_default:
                    insecure.append(name)
            if self.POSTGRES_PASSWORD == _default_db_password:
                insecure.append("POSTGRES_PASSWORD")
            if insecure:
                raise ValueError(
                    f"FATAL: Insecure default values detected for: {', '.join(insecure)}. "
                    f"Set them in your .env file before running in "
                    f"ENVIRONMENT={self.ENVIRONMENT}."
                )

            # LLM Provider: Ollama is development-only
            if self.LLM_PROVIDER == "ollama":
                raise ValueError(
                    "FATAL: LLM_PROVIDER='ollama' is not supported in production. "
                    "Ollama requires too much RAM for VPS deployment. "
                    "Set LLM_PROVIDER=groq in your .env file."
                )
            if not self.GROQ_API_KEY or not self.GROQ_API_KEY.strip():
                raise ValueError(
                    "FATAL: GROQ_API_KEY is required in production. "
                    "Get your API key from: https://console.groq.com/keys"
                )
            if self.GROQ_FALLBACK_TO_OLLAMA:
                raise ValueError(
                    "FATAL: GROQ_FALLBACK_TO_OLLAMA must be False in production. "
                    "Set GROQ_FALLBACK_TO_OLLAMA=false in your .env file."
                )

            # CORS: ensure origins have been explicitly set (no localhost-only)
            _all_local = all(
                "localhost" in o or "127.0.0.1" in o
                for o in self.CORS_ORIGINS
            )
            if _all_local:
                raise ValueError(
                    "CORS_ORIGINS contains only localhost origins. "
                    "Set CORS_ORIGINS in .env for production, e.g.: "
                    'CORS_ORIGINS=["https://grader.example.com"]'
                )

        # Signup invite code validation (all environments)
        if self.SIGNUP_MODE == "invite" and len(self.SIGNUP_INVITE_CODE) < 16:
            # Only warn — DB-managed codes are the primary mechanism now
            if not self.INVITE_SECRET:
                warnings.warn(
                    "SIGNUP_MODE=invite but no INVITE_SECRET set and "
                    "SIGNUP_INVITE_CODE < 16 chars. Set INVITE_SECRET for "
                    "DB-managed codes or SIGNUP_INVITE_CODE for env-var fallback.",
                    UserWarning,
                )

        # INVITE_SECRET validation
        if self.INVITE_SECRET and len(self.INVITE_SECRET) < 32:
            raise ValueError(
                "INVITE_SECRET must be at least 32 characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self
    
    # ==========================================================================
    # LLM Provider Configuration
    # ==========================================================================
    LLM_PROVIDER: str = "ollama"  # "ollama" (dev only) or "groq" (production)
    
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
    
    # ==========================================================================
    # UI Configuration (Gradio — legacy, set via .env if needed)
    # ==========================================================================
    UI_PORT: int = 7860
    UI_HOST: str = "127.0.0.1"
    SHARE_GRADIO: bool = True
    
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

# Ensure critical directories exist on first import
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
settings.USER_WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
settings.GUIDE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
