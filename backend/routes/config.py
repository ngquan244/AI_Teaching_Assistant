"""
Configuration API routes - App Settings
"""
import logging
from typing import Dict
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas import ConfigResponse
from backend.core.config import settings
from backend.auth.dependencies import CurrentUser
from backend.database import get_db
from backend.services.panel_config_service import get_panel_config, PANEL_LABELS

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_model=ConfigResponse)
def get_config(user: CurrentUser):
    """Get current application configuration"""
    return ConfigResponse(
        default_model=settings.DEFAULT_MODEL,
        llm_provider=settings.LLM_PROVIDER,
        groq_available=bool(settings.GROQ_API_KEY),
    )


@router.get("/public")
def get_public_config() -> Dict[str, object]:
    """Public, unauthenticated subset of configuration.

    Used by the frontend to decide which feature flags to surface in the UI
    (e.g. course-shared domain knowledge). Never include secrets.
    """
    return {
        "enable_course_domain_docs": bool(
            getattr(settings, "ENABLE_COURSE_DOMAIN_DOCS", False)
        ),
        "default_domain_quota_ratio": float(
            getattr(settings, "DEFAULT_DOMAIN_QUOTA_RATIO", 0.3)
        ),
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
