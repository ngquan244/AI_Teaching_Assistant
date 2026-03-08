"""
DEPRECATED — This file is a compatibility shim.
All configuration has been consolidated into backend.core.config.

Import from backend.core.config instead:
    from backend.core.config import settings
    from backend.core.config import LLMProviderType
"""
import warnings

warnings.warn(
    "Importing from backend.config is deprecated. "
    "Use 'from backend.core.config import settings' instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export everything for backwards compatibility
from backend.core.config import settings, LLMProviderType, get_settings

__all__ = ["settings", "LLMProviderType", "get_settings"]

