"""
LLM Providers Module
====================
Abstraction layer for swappable LLM backends.
Supports Ollama (local) and Groq Cloud (OpenAI-compatible).
"""

import logging
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage
from langchain_ollama import ChatOllama

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers"""
    OLLAMA = "ollama"
    GROQ = "groq"


class BaseLLM(ABC):
    """
    Abstract base class for LLM providers.
    Provides a unified interface for different LLM backends.
    """
    
    def __init__(
        self,
        model: str,
        temperature: float = 0.3,
        **kwargs
    ):
        self.model = model
        self.temperature = temperature
        self._llm: Optional[BaseChatModel] = None
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name"""
        pass
    
    @abstractmethod
    def _create_llm(self, json_mode: bool = False, max_tokens: Optional[int] = None) -> BaseChatModel:
        """Create and return the underlying LangChain chat model"""
        pass
    
    @property
    def llm(self) -> BaseChatModel:
        """Get the underlying LangChain chat model (lazy initialization)"""
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm
    
    def get_llm(self, json_mode: bool = False, max_tokens: Optional[int] = None) -> BaseChatModel:
        """
        Get LLM instance with optional JSON mode and custom max_tokens.
        
        Args:
            json_mode: If True, configure LLM to output JSON
            max_tokens: Override max output tokens (for dynamic sizing)
            
        Returns:
            LangChain chat model instance
        """
        if json_mode or max_tokens is not None:
            return self._create_llm(json_mode=json_mode, max_tokens=max_tokens)
        return self.llm
    
    def invoke(self, prompt: Union[str, list]) -> AIMessage:
        """
        Invoke the LLM with a prompt.
        
        Args:
            prompt: String prompt or list of messages
            
        Returns:
            AI response message
        """
        return self.llm.invoke(prompt)
    
    @abstractmethod
    def check_connection(self) -> Dict[str, Any]:
        """
        Check if the LLM provider is accessible.
        
        Returns:
            Dictionary with connection status
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """Get provider information"""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "temperature": self.temperature
        }


class OllamaLLM(BaseLLM):
    """
    Ollama LLM provider for local inference.
    """
    
    def __init__(
        self,
        model: str = "llama3.1:latest",
        temperature: float = 0.3,
        base_url: str = "http://localhost:11434",
        num_ctx: int = 4096,
        **kwargs
    ):
        super().__init__(model=model, temperature=temperature, **kwargs)
        self.base_url = base_url
        self.num_ctx = num_ctx
        logger.info(f"OllamaLLM initialized: model={model}, base_url={base_url}")
    
    @property
    def provider_name(self) -> str:
        return LLMProvider.OLLAMA.value
    
    def _create_llm(self, json_mode: bool = False, max_tokens: Optional[int] = None) -> BaseChatModel:
        """Create ChatOllama instance"""
        # For Ollama, max_tokens maps to increased num_ctx (context window = input + output)
        num_ctx = self.num_ctx
        if max_tokens is not None:
            num_ctx = max(self.num_ctx, max_tokens + 4096)  # Ensure room for input + output
        
        kwargs = {
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url,
            "num_ctx": num_ctx,
        }
        
        if json_mode:
            kwargs["format"] = "json"
        
        return ChatOllama(**kwargs)
    
    def check_connection(self) -> Dict[str, Any]:
        """Check Ollama connection"""
        try:
            response = self.llm.invoke("Say 'OK' if you can read this.")
            return {
                "connected": True,
                "provider": self.provider_name,
                "model": self.model,
                "base_url": self.base_url,
                "message": "Ollama connection successful"
            }
        except Exception as e:
            logger.error(f"Ollama connection check failed: {e}")
            return {
                "connected": False,
                "provider": self.provider_name,
                "model": self.model,
                "base_url": self.base_url,
                "error": str(e),
                "message": f"Cannot connect to Ollama: {str(e)}"
            }


class GroqLLM(BaseLLM):
    """
    Groq Cloud LLM provider using OpenAI-compatible API.
    """
    
    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.3,
        api_key: Optional[str] = None,
        base_url: str = "https://api.groq.com/openai/v1",
        max_tokens: int = 8192,
        fallback_to_ollama: bool = True,
        ollama_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        super().__init__(model=model, temperature=temperature, **kwargs)
        
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for Groq provider")
        
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.fallback_to_ollama = fallback_to_ollama
        self.ollama_config = ollama_config or {}
        
        # Import here to avoid dependency issues if openai not installed
        try:
            from langchain_openai import ChatOpenAI
            self._openai_class = ChatOpenAI
        except ImportError:
            raise ImportError(
                "langchain-openai is required for Groq provider. "
                "Install it with: pip install langchain-openai"
            )
        
        logger.info(f"GroqLLM initialized: model={model}, base_url={base_url}")
    
    @property
    def provider_name(self) -> str:
        return LLMProvider.GROQ.value
    
    def _create_llm(self, json_mode: bool = False, max_tokens: Optional[int] = None) -> BaseChatModel:
        """Create ChatOpenAI instance configured for Groq"""
        kwargs = {
            "model": self.model,
            "temperature": self.temperature,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "max_tokens": max_tokens or self.max_tokens,
        }
        
        if json_mode:
            # Groq supports JSON mode via response_format
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        
        return self._openai_class(**kwargs)
    
    def invoke(self, prompt: Union[str, list]) -> AIMessage:
        """
        Invoke Groq with automatic fallback to Ollama on errors.
        
        Handles:
        - 401: Invalid API key
        - 429: Rate limit exceeded
        - Other connection errors
        """
        try:
            return self.llm.invoke(prompt)
        except Exception as e:
            error_str = str(e).lower()
            
            # Check for specific error codes
            is_auth_error = "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str
            is_rate_limit = "429" in error_str or "rate limit" in error_str or "too many requests" in error_str
            
            if is_auth_error:
                logger.error(f"Groq authentication error: {e}")
                error_msg = "Groq API key is invalid or expired"
            elif is_rate_limit:
                logger.warning(f"Groq rate limit exceeded: {e}")
                error_msg = "Groq rate limit exceeded"
            else:
                logger.error(f"Groq API error: {e}")
                error_msg = f"Groq API error: {str(e)}"
            
            # Try fallback to Ollama if enabled
            if self.fallback_to_ollama and self.ollama_config:
                logger.info("Attempting fallback to Ollama...")
                try:
                    ollama_llm = OllamaLLM(**self.ollama_config)
                    return ollama_llm.invoke(prompt)
                except Exception as fallback_error:
                    logger.error(f"Ollama fallback also failed: {fallback_error}")
                    raise RuntimeError(
                        f"{error_msg}. Ollama fallback also failed: {str(fallback_error)}"
                    )
            
            raise RuntimeError(error_msg)
    
    def check_connection(self) -> Dict[str, Any]:
        """Check Groq connection"""
        try:
            response = self.llm.invoke("Say 'OK' if you can read this.")
            return {
                "connected": True,
                "provider": self.provider_name,
                "model": self.model,
                "base_url": self.base_url,
                "message": "Groq connection successful"
            }
        except Exception as e:
            error_str = str(e).lower()
            
            if "401" in error_str or "unauthorized" in error_str:
                error_type = "authentication"
                message = "Invalid Groq API key"
            elif "429" in error_str or "rate limit" in error_str:
                error_type = "rate_limit"
                message = "Groq rate limit exceeded"
            else:
                error_type = "connection"
                message = f"Cannot connect to Groq: {str(e)}"
            
            logger.error(f"Groq connection check failed ({error_type}): {e}")
            
            return {
                "connected": False,
                "provider": self.provider_name,
                "model": self.model,
                "base_url": self.base_url,
                "error": str(e),
                "error_type": error_type,
                "message": message,
                "fallback_available": self.fallback_to_ollama
            }


class LLMFactory:
    """
    Factory class for creating LLM instances.
    Supports runtime switching between providers.
    """
    
    # Class-level current provider (for runtime switching)
    _current_provider: Optional[str] = None
    _current_model: Optional[str] = None
    _instance_cache: Dict[str, BaseLLM] = {}
    
    @classmethod
    def create(
        cls,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> BaseLLM:
        """
        Create an LLM instance based on provider.
        
        Args:
            provider: Provider name ("ollama" or "groq"). 
                     If None, uses environment variable LLM_PROVIDER or defaults to "ollama"
            model: Model name. If None, uses provider-specific default
            **kwargs: Additional provider-specific arguments
            
        Returns:
            BaseLLM instance
        """
        from .config import rag_config
        
        # Determine provider
        if provider is None:
            provider = cls._current_provider or rag_config.LLM_PROVIDER
        
        provider = provider.lower()
        
        # Determine model
        if model is None:
            model = cls._current_model
        
        logger.info(f"Creating LLM: provider={provider}, model={model}")
        
        if provider == LLMProvider.OLLAMA.value:
            return cls._create_ollama(model=model, **kwargs)
        elif provider == LLMProvider.GROQ.value:
            return cls._create_groq(model=model, **kwargs)
        else:
            raise ValueError(f"Unknown LLM provider: {provider}. Supported: ollama, groq")
    
    @classmethod
    def _create_ollama(cls, model: Optional[str] = None, **kwargs) -> OllamaLLM:
        """Create Ollama LLM instance"""
        from .config import rag_config
        
        return OllamaLLM(
            model=model or rag_config.OLLAMA_MODEL,
            temperature=kwargs.get("temperature", rag_config.OLLAMA_TEMPERATURE),
            base_url=kwargs.get("base_url", rag_config.OLLAMA_BASE_URL),
            num_ctx=kwargs.get("num_ctx", rag_config.OLLAMA_NUM_CTX),
        )
    
    @classmethod
    def _create_groq(cls, model: Optional[str] = None, **kwargs) -> GroqLLM:
        """Create Groq LLM instance"""
        from .config import rag_config
        
        if not rag_config.GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY environment variable is required for Groq provider. "
                "Set it in your .env file."
            )
        
        # Prepare Ollama fallback config
        ollama_config = {
            "model": rag_config.OLLAMA_MODEL,
            "temperature": rag_config.OLLAMA_TEMPERATURE,
            "base_url": rag_config.OLLAMA_BASE_URL,
            "num_ctx": rag_config.OLLAMA_NUM_CTX,
        }
        
        return GroqLLM(
            model=model or rag_config.GROQ_MODEL,
            temperature=kwargs.get("temperature", rag_config.OLLAMA_TEMPERATURE),
            api_key=rag_config.GROQ_API_KEY,
            base_url=kwargs.get("base_url", rag_config.GROQ_BASE_URL),
            max_tokens=kwargs.get("max_tokens", 8192),
            fallback_to_ollama=rag_config.GROQ_FALLBACK_TO_OLLAMA,
            ollama_config=ollama_config,
        )
    
    @classmethod
    def set_provider(cls, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Set the current LLM provider at runtime.
        
        Args:
            provider: Provider name ("ollama" or "groq")
            model: Optional model override
            
        Returns:
            Dictionary with status and provider info
        """
        provider = provider.lower()
        
        if provider not in [p.value for p in LLMProvider]:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}. Supported: ollama, groq"
            }
        
        # Validate Groq has API key
        if provider == LLMProvider.GROQ.value:
            from .config import rag_config
            if not rag_config.GROQ_API_KEY:
                return {
                    "success": False,
                    "error": "GROQ_API_KEY is not configured"
                }
        
        cls._current_provider = provider
        cls._current_model = model
        cls._instance_cache.clear()  # Clear cached instances
        
        logger.info(f"LLM provider switched to: {provider}, model: {model}")
        
        return {
            "success": True,
            "provider": provider,
            "model": model,
            "message": f"Successfully switched to {provider}"
        }
    
    @classmethod
    def get_current_provider(cls) -> Dict[str, Any]:
        """Get current provider configuration"""
        from .config import rag_config
        
        provider = cls._current_provider or rag_config.LLM_PROVIDER
        
        if provider == LLMProvider.GROQ.value:
            model = cls._current_model or rag_config.GROQ_MODEL
        else:
            model = cls._current_model or rag_config.OLLAMA_MODEL
        
        return {
            "provider": provider,
            "model": model,
            "available_providers": [p.value for p in LLMProvider]
        }
    
    @classmethod
    def reset(cls):
        """Reset to default provider from config"""
        cls._current_provider = None
        cls._current_model = None
        cls._instance_cache.clear()
        logger.info("LLM provider reset to default from config")
