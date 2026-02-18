"""
Configuration API routes - App Settings
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel

from backend.schemas import ConfigResponse, ModelConfig
from backend.config import settings
from backend.core import BadRequestException, Messages

logger = logging.getLogger(__name__)
router = APIRouter()


class ProviderSwitchRequest(BaseModel):
    provider: str  # "ollama" or "groq"


@router.get("/", response_model=ConfigResponse)
async def get_config():
    """Get current application configuration"""
    return ConfigResponse(
        available_models=settings.AVAILABLE_MODELS,
        default_model=settings.DEFAULT_MODEL,
        max_iterations=settings.MAX_ITERATIONS,
        llm_provider=settings.LLM_PROVIDER,
        groq_available=bool(settings.GROQ_API_KEY),
    )


@router.get("/models")
async def get_models():
    """Get available AI models"""
    return {
        "models": settings.AVAILABLE_MODELS,
        "default": settings.DEFAULT_MODEL,
        "provider": settings.LLM_PROVIDER,
    }


@router.post("/model")
async def set_model(config: ModelConfig):
    """Set AI model configuration (for session)"""
    if config.model not in settings.AVAILABLE_MODELS:
        raise BadRequestException(
            f"Model không hợp lệ. Các model có sẵn: {', '.join(settings.AVAILABLE_MODELS)}"
        )
    
    return {
        "success": True,
        "model": config.model,
        "max_iterations": config.max_iterations,
        "message": f"Đã cấu hình model: {config.model}"
    }


@router.post("/provider")
async def switch_provider(req: ProviderSwitchRequest):
    """Switch LLM provider at runtime (ollama <-> groq)"""
    provider = req.provider.lower().strip()
    if provider not in ("ollama", "groq"):
        raise BadRequestException("Provider không hợp lệ. Chọn 'ollama' hoặc 'groq'.")

    if provider == "groq" and not settings.GROQ_API_KEY:
        raise BadRequestException("Không thể chuyển sang Groq: chưa cấu hình GROQ_API_KEY.")

    # Mutate settings at runtime
    settings.LLM_PROVIDER = provider

    # Clear agent cache so new agents use the new provider
    from backend.services.agent_service import agent_service
    agent_service.clear_cache()

    logger.info(f"LLM provider switched to: {provider}")

    return {
        "success": True,
        "provider": settings.LLM_PROVIDER,
        "default_model": settings.DEFAULT_MODEL,
        "available_models": settings.AVAILABLE_MODELS,
        "message": f"Đã chuyển sang provider: {provider}",
    }
