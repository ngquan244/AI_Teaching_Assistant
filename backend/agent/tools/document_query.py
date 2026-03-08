"""
Document RAG Query Tool
Allows the agent to search and answer questions about uploaded documents.
"""

import json
from typing import Type

from langchain.tools import BaseTool
from pydantic import BaseModel, Field

from .base import logger

__all__ = ["DocumentQueryTool", "DocumentQueryInput", "get_document_query_tool"]


class DocumentQueryInput(BaseModel):
    """Input schema for document query tool"""
    question: str = Field(
        description="Câu hỏi về nội dung tài liệu đã upload (ví dụ: 'Tóm tắt nội dung chính', 'Chương 3 nói về gì?')"
    )


class DocumentQueryTool(BaseTool):
    """
    Tool truy vấn nội dung tài liệu đã upload qua hệ thống RAG.

    Uses the existing RAGService (per-file ChromaDB collections) to retrieve
    relevant chunks and generate an answer with citations.
    """

    name: str = "document_query"
    description: str = """
    Truy vấn và trả lời câu hỏi dựa trên nội dung các tài liệu (PDF) đã được upload vào hệ thống RAG.

    Sử dụng khi người dùng yêu cầu:
    - Tóm tắt nội dung tài liệu đã upload
    - Hỏi đáp về nội dung tài liệu
    - Tìm thông tin trong tài liệu
    - "Tài liệu nói gì về ...?"
    - "Nội dung chính của tài liệu là gì?"

    Tool sẽ:
    1. Tìm kiếm các đoạn văn liên quan trong tài liệu đã upload của người dùng
    2. Trả lời câu hỏi dựa trên nội dung tìm được
    3. Kèm trích dẫn nguồn (tên file, trang)
    """
    args_schema: Type[BaseModel] = DocumentQueryInput
    user_id: str = ""

    def _run(self, question: str) -> str:
        """
        Execute document query via RAG.

        Args:
            question: The question to ask about uploaded documents

        Returns:
            JSON string with answer, citations, or error
        """
        try:
            from backend.modules.document_rag.rag_service import RAGService

            logger.info(f"Document query: {question}")

            rag = RAGService.get_instance()
            rag._ensure_initialized()

            uid = self.user_id or None

            # Check if any documents are indexed
            stats = rag.get_index_stats(user_id=uid)
            total_docs = stats.get("total_documents", 0)
            if total_docs == 0:
                return json.dumps({
                    "error": "Chưa có tài liệu nào được upload vào hệ thống RAG. "
                             "Vui lòng upload tài liệu tại trang 'RAG Tài Liệu' trước.",
                    "status": "no_documents"
                }, ensure_ascii=False, indent=2)

            # Query across user's indexed documents
            result = rag.query(question, user_id=uid)

            if not result:
                return json.dumps({
                    "question": question,
                    "answer": "Không tìm thấy thông tin liên quan trong tài liệu đã upload.",
                    "status": "no_results"
                }, ensure_ascii=False, indent=2)

            # result is typically a dict with 'answer', 'sources', etc.
            if isinstance(result, dict):
                answer = result.get("answer", str(result))
                sources = result.get("sources", [])
            else:
                answer = str(result)
                sources = []

            response = {
                "question": question,
                "answer": answer,
                "sources": sources,
                "total_indexed_documents": total_docs,
                "status": "success"
            }

            logger.info(f"Document query successful, answer length: {len(answer)}")
            return json.dumps(response, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Error querying documents: {e}", exc_info=True)
            return json.dumps({
                "error": f"Lỗi khi truy vấn tài liệu: {str(e)}",
                "status": "error"
            }, ensure_ascii=False, indent=2)

    async def _arun(self, question: str) -> str:
        """Async version — delegates to sync _run."""
        return self._run(question)


def get_document_query_tool(user_id: str = "") -> DocumentQueryTool:
    """Factory that returns a DocumentQueryTool scoped to a specific user."""
    return DocumentQueryTool(user_id=user_id)
