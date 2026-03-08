"""
Configuration API routes - App Settings
"""
import logging
from typing import Dict
from fastapi import APIRouter
from pydantic import BaseModel

from backend.schemas import ConfigResponse, ModelConfig
from backend.core.config import settings
from backend.core import BadRequestException, Messages
from backend.auth.dependencies import CurrentUser, AdminUser
from backend.services.panel_config_service import get_panel_config, PANEL_LABELS
from backend.services.model_config_service import (
    get_model_config,
    get_enabled_providers,
    get_enabled_models,
    is_provider_enabled,
    ALL_PROVIDERS,
    ALL_MODELS,
    PROVIDER_LABELS,
    MODEL_LABELS,
)
from backend.services.tool_config_service import (
    get_enabled_tools,
    TOOL_LABELS,
    TOOL_DESCRIPTIONS,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ProviderSwitchRequest(BaseModel):
    provider: str  # "ollama" or "groq"


@router.get("/", response_model=ConfigResponse)
def get_config(user: CurrentUser):
    """Get current application configuration (filtered by admin model config)"""
    enabled = get_enabled_models(settings.LLM_PROVIDER)
    avail = enabled if enabled else settings.AVAILABLE_MODELS
    return ConfigResponse(
        available_models=avail,
        default_model=settings.DEFAULT_MODEL,
        max_iterations=settings.MAX_ITERATIONS,
        llm_provider=settings.LLM_PROVIDER,
        groq_available=bool(settings.GROQ_API_KEY),
    )


@router.get("/models")
def get_models(user: CurrentUser):
    """Get available AI models (filtered by admin model config)"""
    enabled = get_enabled_models(settings.LLM_PROVIDER)
    avail = enabled if enabled else settings.AVAILABLE_MODELS
    return {
        "models": avail,
        "default": settings.DEFAULT_MODEL,
        "provider": settings.LLM_PROVIDER,
    }


@router.post("/model")
def set_model(config: ModelConfig, user: CurrentUser):
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
def switch_provider(req: ProviderSwitchRequest, admin: AdminUser):
    """Switch LLM provider at runtime (ollama <-> groq)"""
    provider = req.provider.lower().strip()
    if provider not in ("ollama", "groq"):
        raise BadRequestException("Provider không hợp lệ. Chọn 'ollama' hoặc 'groq'.")

    # Ollama is development-only
    if provider == "ollama" and settings.ENVIRONMENT != "development":
        raise BadRequestException(
            "Ollama chỉ khả dụng trong môi trường development. "
            "Production chỉ hỗ trợ Groq Cloud."
        )

    # Check if the provider is enabled by admin
    if not is_provider_enabled(provider):
        raise BadRequestException(f"Provider '{provider}' đã bị admin vô hiệu hóa.")

    if provider == "groq" and not settings.GROQ_API_KEY:
        raise BadRequestException("Không thể chuyển sang Groq: chưa cấu hình GROQ_API_KEY.")

    # Mutate settings at runtime
    settings.LLM_PROVIDER = provider

    # Clear agent cache so new agents use the new provider
    from backend.services.agent_service import agent_service
    agent_service.clear_cache()

    logger.info(f"LLM provider switched to: {provider}")

    # Filter available models through admin config
    enabled = get_enabled_models(provider)
    avail = enabled if enabled else settings.AVAILABLE_MODELS

    return {
        "success": True,
        "provider": settings.LLM_PROVIDER,
        "default_model": settings.DEFAULT_MODEL,
        "available_models": avail,
        "message": f"Đã chuyển sang provider: {provider}",
    }


# =============================================================================
# Panel Visibility (public – any authenticated user can read)
# =============================================================================

@router.get("/panels")
def get_panels_config(user: CurrentUser) -> Dict[str, object]:
    """
    Get panel visibility configuration.
    Returns which panels are enabled/disabled so the frontend can hide them.
    """
    config = get_panel_config()
    return {
        "panels": config,
        "labels": PANEL_LABELS,
    }


# =============================================================================
# Model / Provider Visibility (public – any authenticated user can read)
# =============================================================================

@router.get("/models-config")
def get_models_config(user: CurrentUser) -> Dict[str, object]:
    """
    Get model/provider visibility config for the frontend.
    Returns enabled providers, enabled models per provider, and labels.
    """
    enabled_providers = get_enabled_providers()
    enabled_models = {
        p: get_enabled_models(p) for p in enabled_providers
    }
    return {
        "enabled_providers": enabled_providers,
        "enabled_models": enabled_models,
        "provider_labels": PROVIDER_LABELS,
        "model_labels": MODEL_LABELS,
    }


# =============================================================================
# Tool Visibility (public – any authenticated user can read)
# =============================================================================

@router.get("/tools-config")
def get_tools_config(user: CurrentUser) -> Dict[str, object]:
    """
    Get tool visibility config for the frontend.
    Returns list of enabled tool names and labels.
    """
    enabled = get_enabled_tools()
    return {
        "enabled_tools": enabled,
        "tool_labels": TOOL_LABELS,
        "tool_descriptions": TOOL_DESCRIPTIONS,
    }
