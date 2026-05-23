"""
LLM Providers Module
====================
Abstraction layer for LLM backends.
Currently supports Groq Cloud (OpenAI-compatible).
"""

import logging
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union
from enum import Enum

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers"""
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
        key_id: Optional[str] = None,
        masked_key: Optional[str] = None,
        **kwargs
    ):
        super().__init__(model=model, temperature=temperature, **kwargs)
        
        if not api_key:
            raise ValueError("GROQ_API_KEY is required for Groq provider")
        
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        # KeyPool identifiers used for per-request logging. Both optional so
        # single-key (env) usage still works.
        self.key_id = key_id
        self.masked_key = masked_key or (
            f"{api_key[:6]}...{api_key[-4:]}" if api_key and len(api_key) > 10 else "***"
        )
        
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
            # Let KeyPool handle rate-limit rotation instead of SDK-level retries.
            "max_retries": 0,
        }
        
        if json_mode:
            # Groq supports JSON mode via response_format
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        
        return self._openai_class(**kwargs)
    
    def invoke(self, prompt: Union[str, list]) -> AIMessage:
        """
        Invoke Groq LLM.
        
        Handles:
        - 401: Invalid API key
        - 429: Rate limit exceeded
        - Other connection errors
        """
        t0 = time.monotonic()
        logger.info(
            "LLM_REQUEST_START provider=groq model=%s key_id=%s masked_key=%s",
            self.model, self.key_id or "-", self.masked_key,
        )
        try:
            result = self.llm.invoke(prompt)
            logger.info(
                "LLM_REQUEST_SUCCESS key_id=%s masked_key=%s duration_ms=%d",
                self.key_id or "-", self.masked_key,
                int((time.monotonic() - t0) * 1000),
            )
            return result
        except Exception as e:
            error_str = str(e).lower()
            duration_ms = int((time.monotonic() - t0) * 1000)
            
            if "401" in error_str or "unauthorized" in error_str or "invalid api key" in error_str:
                logger.error(
                    "LLM_REQUEST_AUTH_ERROR key_id=%s masked_key=%s duration_ms=%d error=%s",
                    self.key_id or "-", self.masked_key, duration_ms, e,
                )
                raise RuntimeError("Groq API key is invalid or expired")
            elif "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
                logger.warning(
                    "LLM_REQUEST_429 key_id=%s masked_key=%s duration_ms=%d error=%s",
                    self.key_id or "-", self.masked_key, duration_ms, e,
                )
                raise RuntimeError("Groq rate limit exceeded")
            else:
                logger.error(
                    "LLM_REQUEST_ERROR key_id=%s masked_key=%s duration_ms=%d error=%s",
                    self.key_id or "-", self.masked_key, duration_ms, e,
                )
                raise RuntimeError(f"Groq API error: {str(e)}")
    
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
        groq_api_key: Optional[str] = None,
        key_id: Optional[str] = None,
        masked_key: Optional[str] = None,
        **kwargs
    ) -> BaseLLM:
        """
        Create an LLM instance.
        
        Args:
            provider: Provider name ("groq"). 
                     If None, uses environment variable LLM_PROVIDER
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
        
        if provider == LLMProvider.GROQ.value:
            return cls._create_groq(
                model=model,
                groq_api_key=groq_api_key,
                key_id=key_id,
                masked_key=masked_key,
                **kwargs,
            )
        else:
            raise ValueError(f"Unknown LLM provider: {provider}. Only 'groq' is supported.")
    
    @classmethod
    def _create_groq(
        cls,
        model: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        key_id: Optional[str] = None,
        masked_key: Optional[str] = None,
        **kwargs,
    ) -> GroqLLM:
        """Create Groq LLM instance"""
        from .config import rag_config

        effective_key = groq_api_key or rag_config.GROQ_API_KEY
        if not effective_key:
            raise ValueError(
                "GROQ_API_KEY is required for Groq provider. "
                "Set it via the admin panel or in your .env file."
            )
        
        return GroqLLM(
            model=model or rag_config.GROQ_MODEL,
            temperature=kwargs.get("temperature", rag_config.GROQ_TEMPERATURE),
            api_key=effective_key,
            base_url=kwargs.get("base_url", rag_config.GROQ_BASE_URL),
            max_tokens=kwargs.get("max_tokens", 8192),
            key_id=key_id,
            masked_key=masked_key,
        )
    
    @classmethod
    def set_provider(cls, provider: str, model: Optional[str] = None) -> Dict[str, Any]:
        """
        Set the current LLM provider at runtime.
        
        Args:
            provider: Provider name ("groq")
            model: Optional model override
            
        Returns:
            Dictionary with status and provider info
        """
        provider = provider.lower()
        
        if provider not in [p.value for p in LLMProvider]:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}. Only 'groq' is supported."
            }
        
        from .config import rag_config
        if not rag_config.GROQ_API_KEY:
            return {
                "success": False,
                "error": "GROQ_API_KEY is not configured"
            }
        
        cls._current_provider = provider
        cls._current_model = model
        cls._instance_cache.clear()
        
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
        model = cls._current_model or rag_config.GROQ_MODEL
        
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
