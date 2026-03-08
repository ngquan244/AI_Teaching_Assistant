"""
Model Config Service
====================
Manages which LLM providers and models are enabled/disabled by admin.
Config is stored as a JSON file in the data/ directory.
Disabled providers/models won't appear in teacher UI.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All known providers and their models (must match backend/config.py lists)
# ---------------------------------------------------------------------------
ALL_PROVIDERS = ["ollama", "groq"]

PROVIDER_LABELS: Dict[str, str] = {
    "ollama": "Ollama (Local)",
    "groq": "Groq Cloud",
}

PROVIDER_DESCRIPTIONS: Dict[str, str] = {
    "ollama": "Chạy LLM trên máy local bằng Ollama. Yêu cầu cài Ollama.",
    "groq": "Inference siêu nhanh qua Groq LPU cloud. Yêu cầu API key.",
}

ALL_MODELS: Dict[str, List[str]] = {
    "ollama": [
        "llama3.1:latest",
        "phi3:latest",
        "mistral:latest",
        "gemma2:latest",
    ],
    "groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
        "mixtral-8x7b-32768",
    ],
}

MODEL_LABELS: Dict[str, str] = {
    # Ollama
    "llama3.1:latest": "Llama 3.1 (Latest)",
    "phi3:latest": "Phi-3 (Latest)",
    "mistral:latest": "Mistral (Latest)",
    "gemma2:latest": "Gemma 2 (Latest)",
    # Groq
    "llama-3.3-70b-versatile": "Llama 3.3 70B Versatile",
    "llama-3.1-8b-instant": "Llama 3.1 8B Instant",
    "gemma2-9b-it": "Gemma 2 9B IT",
    "mixtral-8x7b-32768": "Mixtral 8x7B 32K",
}

CONFIG_FILE = Path("data/model_config.json")


# ---------------------------------------------------------------------------
# Default config — everything enabled
# ---------------------------------------------------------------------------

def _default_config() -> Dict[str, Any]:
    return {
        "providers": {p: True for p in ALL_PROVIDERS},
        "models": {
            provider: {model: True for model in models}
            for provider, models in ALL_MODELS.items()
        },
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_model_config() -> Dict[str, Any]:
    """Read model config from disk. Returns default if file missing."""
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            config = _default_config()
            # Merge providers
            if "providers" in data:
                for p in ALL_PROVIDERS:
                    if p in data["providers"]:
                        config["providers"][p] = bool(data["providers"][p])
            # Merge models
            if "models" in data:
                for provider, models in ALL_MODELS.items():
                    if provider in data["models"]:
                        for m in models:
                            if m in data["models"][provider]:
                                config["models"][provider][m] = bool(
                                    data["models"][provider][m]
                                )
            return config
    except Exception as e:
        logger.warning("Failed to read model config, using defaults: %s", e)
    return _default_config()


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def update_model_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update model config. Accepts partial updates."""
    config = get_model_config()

    if "providers" in updates:
        for p, enabled in updates["providers"].items():
            if p in ALL_PROVIDERS:
                config["providers"][p] = bool(enabled)

    if "models" in updates:
        for provider, model_map in updates["models"].items():
            if provider in ALL_MODELS:
                for m, enabled in model_map.items():
                    if m in ALL_MODELS[provider]:
                        config["models"][provider][m] = bool(enabled)

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Model config updated: %s", config)
    return config


# ---------------------------------------------------------------------------
# Convenience helpers (used by config routes to filter)
# ---------------------------------------------------------------------------

def get_enabled_providers() -> List[str]:
    """Return list of provider keys that are enabled.
    In non-development environments, Ollama is excluded."""
    from backend.core.config import settings
    cfg = get_model_config()
    providers = [p for p in ALL_PROVIDERS if cfg["providers"].get(p, True)]
    # Ollama is development-only
    if settings.ENVIRONMENT != "development":
        providers = [p for p in providers if p != "ollama"]
    return providers


def get_enabled_models(provider: str) -> List[str]:
    """Return list of model names enabled for a given provider."""
    cfg = get_model_config()
    if provider not in ALL_MODELS:
        return []
    return [
        m
        for m in ALL_MODELS[provider]
        if cfg["models"].get(provider, {}).get(m, True)
    ]


def is_provider_enabled(provider: str) -> bool:
    """Check if a specific provider is enabled.
    Ollama is always disabled in non-development environments."""
    from backend.core.config import settings
    if provider == "ollama" and settings.ENVIRONMENT != "development":
        return False
    cfg = get_model_config()
    return cfg["providers"].get(provider, True)
