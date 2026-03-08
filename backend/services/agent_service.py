"""
AI Agent Service
Handles AI model interactions and agent management
Supports Ollama (local) and Groq (cloud) LLM providers
"""
import logging
from typing import Dict, List, Optional, Any
from functools import lru_cache

logger = logging.getLogger(__name__)


def _get_provider_config() -> dict:
    """Load LLM provider configuration from settings"""
    from backend.core.config import settings
    return {
        "provider": settings.LLM_PROVIDER,
        "groq_api_key": settings.GROQ_API_KEY,
        "groq_base_url": settings.GROQ_BASE_URL,
        "ollama_base_url": settings.OLLAMA_BASE_URL,
        "groq_fallback_to_ollama": settings.GROQ_FALLBACK_TO_OLLAMA if settings.ENVIRONMENT == "development" else False,
        "ollama_fallback_model": settings.OLLAMA_MODEL,
    }


class AgentService:
    """Service for managing AI agents"""
    
    _instance: Optional["AgentService"] = None
    _agent_cache: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_agent(self, model: str, max_iterations: int, user_id: Optional[str] = None):
        """Get or create an agent instance"""
        provider_cfg = _get_provider_config()
        # Include user_id in cache key so each user gets their own agent
        # (tools are bound with user-specific paths)
        user_key = user_id or "anonymous"
        cache_key = f"{provider_cfg['provider']}_{model}_{max_iterations}_{user_key}"
        
        if cache_key not in self._agent_cache:
            logger.info(f"Creating new agent: {cache_key}")
            from backend.agent.agent_graph import create_agent
            self._agent_cache[cache_key] = create_agent(
                model=model,
                max_iterations=max_iterations,
                user_id=user_id,
                **provider_cfg,
            )
        
        return self._agent_cache[cache_key]
    
    def invoke(
        self,
        message: str,
        history: List[Dict[str, str]],
        model: str,
        max_iterations: int,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Invoke the AI agent with a message"""
        agent = self.get_agent(model, max_iterations, user_id=user_id)
        return agent.invoke(message, history)
    
    def clear_cache(self):
        """Clear the agent cache"""
        self._agent_cache.clear()
        logger.info("Agent cache cleared")


# Singleton instance
agent_service = AgentService()
