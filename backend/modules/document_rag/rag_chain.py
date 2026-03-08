"""
RAG Chain Module
================
Build and execute the RAG chain using configurable LLM backends.
Supports Ollama (local) and Groq Cloud (API).
"""

import logging
from typing import List, Dict, Any, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from .config import rag_config
from .retriever import DocumentRetriever
from .llm_providers import BaseLLM, LLMFactory

logger = logging.getLogger(__name__)


# RAG Prompt Template
RAG_PROMPT_TEMPLATE = """Bạn là một trợ lý AI chuyên trả lời câu hỏi dựa trên tài liệu được cung cấp.

NGUYÊN TẮC QUAN TRỌNG:
1. CHỈ trả lời dựa trên thông tin trong phần Context bên dưới
2. Nếu Context không chứa đủ thông tin để trả lời, hãy nói rõ: "Không tìm thấy thông tin liên quan trong tài liệu"
3. KHÔNG bịa đặt hoặc sử dụng kiến thức bên ngoài
4. Trả lời ngắn gọn, rõ ràng và chính xác
5. Nếu có thể, trích dẫn nguồn (trang, phần) khi trả lời

CONTEXT TỪ TÀI LIỆU:
{context}

CÂU HỎI: {question}

TRẢ LỜI:"""


class RAGChain:
    """
    RAG Chain for question answering using configurable LLM backends.
    
    Features:
    - Supports multiple LLM providers (Ollama, Groq)
    - Returns answers with source citations
    - Configurable model and parameters
    - Runtime provider switching
    """
    
    def __init__(
        self,
        retriever: DocumentRetriever,
        llm_provider: Optional[BaseLLM] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize RAG chain.
        
        Args:
            retriever: DocumentRetriever instance
            llm_provider: Pre-configured LLM provider (if None, uses LLMFactory)
            model: Model name override (legacy, for backwards compatibility)
            temperature: Generation temperature (legacy)
            base_url: API base URL (legacy)
        """
        self.retriever = retriever
        
        # Store legacy params for backwards compatibility
        self._model_override = model
        self._temperature_override = temperature
        self._base_url_override = base_url
        
        # Initialize LLM provider
        self._llm_provider: Optional[BaseLLM] = llm_provider
        
        # Initialize prompt
        self.prompt = ChatPromptTemplate.from_template(RAG_PROMPT_TEMPLATE)
        
        # Initialize LLM if provider was passed
        if self._llm_provider is None:
            self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM using factory."""
        logger.info("Initializing LLM via factory...")
        
        # Build kwargs for factory
        kwargs = {}
        if self._temperature_override is not None:
            kwargs["temperature"] = self._temperature_override
        if self._base_url_override is not None:
            kwargs["base_url"] = self._base_url_override
        
        self._llm_provider = LLMFactory.create(
            model=self._model_override,
            **kwargs
        )
        
        info = self._llm_provider.get_info()
        logger.info(f"LLM initialized: provider={info['provider']}, model={info['model']}")
    
    @property
    def llm(self):
        """Get the underlying LangChain LLM instance."""
        if self._llm_provider is None:
            self._init_llm()
        return self._llm_provider.llm
    
    @property
    def model(self) -> str:
        """Get current model name."""
        if self._llm_provider:
            return self._llm_provider.model
        return self._model_override or rag_config.OLLAMA_MODEL
    
    @property
    def base_url(self) -> str:
        """Get current base URL."""
        if self._llm_provider and hasattr(self._llm_provider, 'base_url'):
            return self._llm_provider.base_url
        return self._base_url_override or rag_config.OLLAMA_BASE_URL
    
    def set_llm_provider(self, provider: BaseLLM):
        """
        Set a new LLM provider at runtime.
        
        Args:
            provider: New LLM provider instance
        """
        self._llm_provider = provider
        info = provider.get_info()
        logger.info(f"LLM provider updated: {info['provider']}, model={info['model']}")
    
    def query(
        self,
        question: str,
        k: Optional[int] = None,
        return_context: bool = False,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute RAG query.
        
        Args:
            question: User's question
            k: Number of documents to retrieve
            return_context: Whether to include retrieved context in response
            target_file_hashes: File hashes to scope the retrieval
            user_id: User ID to scope the retrieval
            
        Returns:
            Dictionary with:
            - answer: Generated answer
            - sources: List of source citations
            - context: (optional) Retrieved context text
        """
        logger.info(f"RAG Query: {question}")
        
        # Step 1: Retrieve relevant documents
        # Pass target_file_hashes and user_id if retriever supports them
        retrieve_kwargs: Dict[str, Any] = {"k": k} if k else {}
        if hasattr(self.retriever, 'resolve_target_file_hashes'):
            retrieve_kwargs["target_file_hashes"] = target_file_hashes
            retrieve_kwargs["user_id"] = user_id
        documents = self.retriever.retrieve(question, **retrieve_kwargs)
        
        if not documents:
            return {
                "answer": "Không tìm thấy thông tin liên quan trong tài liệu.",
                "sources": [],
                "context": "" if return_context else None
            }
        
        # Step 2: Format context
        context = self.retriever.format_context(documents)
        
        # Step 3: Build and run chain
        chain = self.prompt | self.llm
        
        try:
            logger.info("Generating answer with Ollama...")
            
            response = chain.invoke({
                "context": context,
                "question": question
            })
            
            answer = response.content if hasattr(response, 'content') else str(response)
            
            logger.info("Answer generated successfully")
            
        except Exception as e:
            logger.error(f"Error generating answer: {e}")
            return {
                "answer": f"Lỗi khi tạo câu trả lời: {str(e)}",
                "sources": [],
                "context": context if return_context else None,
                "error": str(e)
            }
        
        # Step 4: Extract citations
        sources = self.retriever.extract_citations(documents)
        
        # Build response
        result = {
            "answer": answer,
            "sources": sources
        }
        
        if return_context:
            result["context"] = context
        
        return result
    
    def query_with_custom_prompt(
        self,
        question: str,
        prompt_template: str,
        k: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Execute RAG query with a custom prompt template.
        
        Args:
            question: User's question
            prompt_template: Custom prompt template (must have {context} and {question})
            k: Number of documents to retrieve
            
        Returns:
            Dictionary with answer and sources
        """
        # Retrieve documents
        documents = self.retriever.retrieve(question, k=k)
        
        if not documents:
            return {
                "answer": "Không tìm thấy thông tin liên quan trong tài liệu.",
                "sources": []
            }
        
        # Format context
        context = self.retriever.format_context(documents)
        
        # Use custom prompt
        custom_prompt = ChatPromptTemplate.from_template(prompt_template)
        chain = custom_prompt | self.llm
        
        try:
            response = chain.invoke({
                "context": context,
                "question": question
            })
            answer = response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Error with custom prompt: {e}")
            return {
                "answer": f"Lỗi: {str(e)}",
                "sources": [],
                "error": str(e)
            }
        
        sources = self.retriever.extract_citations(documents)
        
        return {
            "answer": answer,
            "sources": sources
        }
    
    def check_ollama_connection(self) -> Dict[str, Any]:
        """
        Check if the LLM provider is accessible.
        Kept for backwards compatibility - now checks current provider.
        
        Returns:
            Dictionary with connection status
        """
        if self._llm_provider is None:
            self._init_llm()
        
        return self._llm_provider.check_connection()
    
    def check_connection(self) -> Dict[str, Any]:
        """
        Check if the current LLM provider is accessible.
        
        Returns:
            Dictionary with connection status
        """
        return self.check_ollama_connection()
