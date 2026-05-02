"""
Document RAG API Routes
=======================
FastAPI routes for the Document RAG feature.
Completely independent from existing chatbot routes.
"""

import os
import io
import shutil
import hashlib
import json
import logging
import zipfile
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from backend.auth.dependencies import CurrentUser, AdminUser
from backend.modules.document_rag import RAGService
from backend.core.config import settings
from backend.core.logger import quiz_logger
from backend.utils import get_user_rag_dir
from backend.database.base import SessionLocal
from backend.services.url_safety import validate_download_url

logger = logging.getLogger(__name__)

router = APIRouter()

# ===== Upload limits =====
# Hard cap on PDF uploads. Larger than this and the worker would spend
# minutes parsing while the user just sees a spinner -> bad UX.
MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
PDF_MAGIC = b"%PDF-"


def _validate_pdf_upload(file: UploadFile) -> None:
    """
    Reject PDF uploads that are obviously bad before we touch the disk.

    Checks (in order):
      * filename ends with .pdf
      * declared content_type is application/pdf (best-effort: many browsers
        send empty / octet-stream, so this is a soft check)
      * size <= MAX_PDF_SIZE_BYTES (when reported by the client)

    Magic-byte verification happens after the file lands on disk so we can
    also delete the bogus file. See ``_assert_pdf_magic_bytes``.
    """
    name = (file.filename or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Tên tệp không hợp lệ.")
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tệp PDF.")

    declared_type = (file.content_type or "").lower()
    # Browsers sometimes omit content_type; only reject when it is set AND wrong.
    if declared_type and declared_type not in ("application/pdf", "application/octet-stream", "binary/octet-stream"):
        raise HTTPException(
            status_code=400,
            detail=f"Tệp phải là PDF (nhận được: {declared_type}).",
        )

    size = getattr(file, "size", None)
    if size is not None and size > MAX_PDF_SIZE_BYTES:
        mb = size / (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=(
                f"Tệp quá lớn ({mb:.1f} MB). Giới hạn là "
                f"{MAX_PDF_SIZE_BYTES // (1024 * 1024)} MB."
            ),
        )


def _assert_pdf_magic_bytes(path: Path) -> None:
    """Ensure the uploaded file actually starts with the PDF magic header.
    Removes the file and raises 400 if not."""
    try:
        with open(path, "rb") as f:
            header = f.read(len(PDF_MAGIC))
    except OSError:
        header = b""
    if header != PDF_MAGIC:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(
            status_code=400,
            detail="Tệp không phải định dạng PDF hợp lệ (magic bytes sai).",
        )


def _generate_quiz_idempotency_key(
    *,
    scope: str,
    user_id: str,
    topics: List[str],
    num_questions: int,
    difficulty: str,
    language: str,
    selected_documents: Optional[List[str]] = None,
    extra: Optional[dict] = None,
) -> str:
    """
    Build a stable idempotency key for an async quiz-generation request.

    Two requests with the same (user, topics, settings, scope) within the
    in-flight window will be coalesced into a single job, preventing
    duplicate Groq quota burn from accidental double-clicks.

    The key is intentionally insensitive to topic ordering so the UI can
    pass topics in any order without breaking dedupe.
    """
    canon = {
        "scope": scope,
        "user_id": user_id,
        "topics": sorted(t.strip() for t in topics if t and t.strip()),
        "num_questions": int(num_questions),
        "difficulty": (difficulty or "").lower().strip(),
        "language": (language or "").lower().strip(),
        "selected_documents": sorted(selected_documents) if selected_documents else None,
        "extra": extra or None,
    }
    blob = json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()
    return f"genquiz:{scope}:{digest}"


# ===== Request/Response Models =====

class QueryRequest(BaseModel):
    """Request model for RAG query"""
    question: str
    k: Optional[int] = None
    return_context: bool = False
    file_hashes: Optional[List[str]] = None  # Query specific files by hash
    selected_documents: Optional[List[str]] = None  # Query specific files by filename


class QueryResponse(BaseModel):
    """Response model for RAG query"""
    success: bool
    answer: str
    sources: list
    context: Optional[str] = None
    error: Optional[str] = None


class IndexStatsResponse(BaseModel):
    """Response model for index statistics"""
    success: bool
    stats: dict


class IngestResponse(BaseModel):
    """Response model for document ingestion"""
    success: bool
    message: str
    filename: Optional[str] = None
    file_hash: Optional[str] = None
    pages_loaded: Optional[int] = None
    chunks_added: Optional[int] = None
    already_indexed: bool = False
    error: Optional[str] = None


class GenerateQuizRequest(BaseModel):
    """Request model for quiz generation"""
    topic: str = ""  # Single topic (legacy support)
    topics: Optional[List[str]] = None  # Multiple topics (new)
    num_questions: int = 5
    difficulty: str = "medium"  # easy, medium, hard
    language: str = "vi"  # vi, en
    k: int = 10
    selected_documents: Optional[List[str]] = None  # Selected document filenames


class QuizQuestion(BaseModel):
    """Model for a single quiz question"""
    question_number: int
    question: str
    options: dict
    correct_answer: str


class GenerateQuizResponse(BaseModel):
    """Response model for quiz generation"""
    success: bool
    partial: bool = False
    questions: list = []
    topic: str = ""
    num_questions_requested: Optional[int] = None
    num_questions_generated: Optional[int] = None
    context_used: Optional[str] = None
    raw_response: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


# ===== Helper Functions =====

def get_rag_service() -> RAGService:
    """Get RAG service singleton instance"""
    return RAGService.get_instance()


# ===== API Endpoints =====

@router.post("/upload", response_model=IngestResponse)
def upload_document(user: CurrentUser, file: UploadFile = File(...)):
    """
    Upload a PDF document for RAG.
    
    This endpoint only saves the file. Use /build-index to index it.
    """
    logger.info(f"Uploading document: {file.filename} (user={user.id})")
    
    # Validate file (extension, content_type, size)
    _validate_pdf_upload(file)
    
    try:
        # Per-user upload directory
        user_upload_dir = get_user_rag_dir(str(user.id))
        file_path = user_upload_dir / file.filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Verify magic bytes after writing (cheap; deletes file if bogus)
        _assert_pdf_magic_bytes(file_path)
        
        logger.debug(f"File saved to: {file_path}")
        
        return IngestResponse(
            success=True,
            message=f"File uploaded successfully: {file.filename}",
            filename=file.filename
        )
        
    except Exception as e:
        logger.exception("Error uploading file")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/build-index", response_model=IngestResponse, deprecated=True)
def build_index(user: CurrentUser, filename: str = Form(...)):
    """
    Build/update the vector index for an uploaded document.
    
    **DEPRECATED**: Use POST /async/build-index instead.

    Args:
        filename: Name of the uploaded file to index
    """
    logger.warning("DEPRECATED sync endpoint /build-index called — migrate to /async/build-index")
    logger.info(f"Building index for: {filename} (user={user.id})")
    
    user_upload_dir = get_user_rag_dir(str(user.id))
    file_path = user_upload_dir / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.ingest_document(str(file_path), user_id=str(user.id), db_session=db)
        
        return IngestResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            filename=result.get("filename"),
            file_hash=result.get("file_hash"),
            pages_loaded=result.get("pages_loaded"),
            chunks_added=result.get("chunks_added"),
            already_indexed=result.get("already_indexed", False),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.exception("Error building index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/upload-and-index", response_model=IngestResponse, deprecated=True)
def upload_and_index(user: CurrentUser, file: UploadFile = File(...)):
    """
    Upload and immediately index a PDF document.
    
    **DEPRECATED**: Use POST /async/upload-and-index instead.
    """
    logger.warning("DEPRECATED sync endpoint /upload-and-index called — migrate to /async/upload-and-index")
    logger.info(f"Upload and index: {file.filename} (user={user.id})")
    
    # Validate file (extension, content_type, size)
    _validate_pdf_upload(file)
    
    try:
        # Per-user upload directory
        user_upload_dir = get_user_rag_dir(str(user.id))
        file_path = user_upload_dir / file.filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Verify magic bytes after writing (cheap; deletes file if bogus)
        _assert_pdf_magic_bytes(file_path)
        
        logger.debug(f"File saved to: {file_path}")
        
        # Index the document
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.ingest_document(str(file_path), user_id=str(user.id), db_session=db)
        
        return IngestResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            filename=result.get("filename"),
            file_hash=result.get("file_hash"),
            pages_loaded=result.get("pages_loaded"),
            chunks_added=result.get("chunks_added"),
            already_indexed=result.get("already_indexed", False),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.exception("Error in upload-and-index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


class DownloadAndIndexRequest(BaseModel):
    """Request model for downloading and indexing from URL"""
    url: str
    filename: str


@router.post("/download-and-index", response_model=IngestResponse)
async def download_and_index(request: DownloadAndIndexRequest, user: CurrentUser):
    """
    Download a PDF from URL and index it.
    
    Used for Canvas LMS integration where files have signed download URLs.
    """
    import asyncio
    import httpx
    
    logger.info(f"Download and index: {request.filename} from URL (user={user.id})")
    
    # Validate filename
    if not request.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tệp PDF.")
    
    try:
        # Download file from URL (follow redirects like curl -L) — async I/O
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(validate_download_url(request.url))
            response.raise_for_status()
            content = response.content
        
        # Enforce same size cap as direct uploads.
        if len(content) > MAX_PDF_SIZE_BYTES:
            mb = len(content) / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Tệp tải về quá lớn ({mb:.1f} MB). Giới hạn là "
                    f"{MAX_PDF_SIZE_BYTES // (1024 * 1024)} MB."
                ),
            )
        if not content.startswith(PDF_MAGIC):
            raise HTTPException(
                status_code=400,
                detail="Tệp tải về không phải định dạng PDF hợp lệ.",
            )
        
        # Sanitize filename
        safe_filename = "".join(c for c in request.filename if c.isalnum() or c in "._- ")
        if not safe_filename:
            safe_filename = "downloaded_file.pdf"
        if not safe_filename.lower().endswith('.pdf'):
            safe_filename += '.pdf'
        
        # Save file
        user_upload_dir = get_user_rag_dir(str(user.id))
        file_path = user_upload_dir / safe_filename
        
        # Ensure unique filename
        counter = 1
        base_name = file_path.stem
        while file_path.exists():
            file_path = user_upload_dir / f"{base_name}_{counter}.pdf"
            counter += 1
        
        # Save + index in threadpool to avoid blocking event loop
        user_id = str(user.id)
        def _save_and_ingest():
            with open(file_path, "wb") as f:
                f.write(content)
            logger.debug(f"File downloaded and saved to: {file_path}")
            rag_service = get_rag_service()
            with SessionLocal() as db:
                return rag_service.ingest_document(str(file_path), user_id=user_id, db_session=db)

        result = await asyncio.to_thread(_save_and_ingest)
        
        return IngestResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            filename=result.get("filename"),
            file_hash=result.get("file_hash"),
            pages_loaded=result.get("pages_loaded"),
            chunks_added=result.get("chunks_added"),
            already_indexed=result.get("already_indexed", False),
            error=result.get("error")
        )
        
    except httpx.HTTPStatusError as e:
        logger.exception("HTTP error downloading file")
        raise HTTPException(status_code=502, detail="Lỗi tải file từ server")
    except httpx.RequestError as e:
        logger.error(f"Network error downloading file: {e}")
        raise HTTPException(status_code=502, detail="Network error during download")
    except Exception as e:
        logger.exception("Error in download-and-index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/query", response_model=QueryResponse)
def query_documents(request: QueryRequest, user: CurrentUser):
    """
    Query the document knowledge base.
    
    Queries are scoped to specific per-file collections when file_hashes
    or selected_documents are provided. Otherwise queries all indexed files.
    
    Args:
        request: Query request with question and optional file selection
        
    Returns:
        Answer with source citations
    """
    logger.info(f"RAG Query: {request.question}")
    
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.query(
                question=request.question,
                k=request.k,
                return_context=request.return_context,
                file_hashes=request.file_hashes,
                selected_documents=request.selected_documents,
                user_id=str(user.id),
                db_session=db,
            )
        
        return QueryResponse(
            success=result.get("success", False),
            answer=result.get("answer", ""),
            sources=result.get("sources", []),
            context=result.get("context"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.exception("Error processing query")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/stats", response_model=IndexStatsResponse)
def get_index_stats(user: CurrentUser):
    """
    Get statistics about the document index.
    """
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            stats = rag_service.get_index_stats(user_id=str(user.id), db_session=db)
        
        return IndexStatsResponse(
            success=True,
            stats=stats
        )
        
    except Exception as e:
        logger.exception("Error getting stats")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/reset")
def reset_index(user: CurrentUser):
    """
    Reset the document index for the current user.

    Also wipes every uploaded PDF in the user's upload directory so
    "Xóa toàn bộ dữ liệu" matches the label users see in the UI.
    """
    logger.warning(f"Resetting document index for user={user.id}")
    
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.reset_index(user_id=str(user.id), db_session=db)

        # Best-effort cleanup of uploaded PDFs (index reset alone leaves
        # the source files behind, which is confusing for end users).
        deleted_files = 0
        try:
            user_upload_dir = get_user_rag_dir(str(user.id))
            for pdf_path in user_upload_dir.glob("*.pdf"):
                try:
                    pdf_path.unlink()
                    deleted_files += 1
                except OSError as fs_err:
                    logger.warning(f"Could not delete uploaded file {pdf_path}: {fs_err}")
        except Exception as fs_err:
            logger.warning(f"Could not enumerate user upload dir for reset: {fs_err}")

        if isinstance(result, dict):
            result["deleted_files"] = deleted_files
        return result
        
    except Exception as e:
        logger.exception("Error resetting index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/config")
def get_rag_config(user: CurrentUser):
    """
    Get current RAG configuration.
    """
    try:
        rag_service = get_rag_service()
        config = rag_service.get_config()
        
        return {
            "success": True,
            "config": config
        }
        
    except Exception as e:
        logger.exception("Error getting config")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/uploaded-files")
def list_uploaded_files(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """
    List uploaded PDF files for the current user (paginated).
    """
    try:
        user_upload_dir = get_user_rag_dir(str(user.id))
        files = []
        for file_path in user_upload_dir.glob("*.pdf"):
            stat = file_path.stat()
            files.append({
                "filename": file_path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime
            })
        
        # Sort newest first, then paginate
        files.sort(key=lambda f: f["modified"], reverse=True)
        total = len(files)
        offset = (page - 1) * page_size
        files = files[offset:offset + page_size]
        
        return {
            "success": True,
            "files": files,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 1,
        }
        
    except Exception as e:
        logger.exception("Error listing files")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.delete("/uploaded-files/{filename}")
def delete_uploaded_file(filename: str, user: CurrentUser):
    """
    Delete an uploaded file.
    
    Note: This does not remove it from the index.
    Use /reset to clear the index.
    """
    file_path = get_user_rag_dir(str(user.id)) / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    
    try:
        os.remove(file_path)
        
        return {
            "success": True,
            "message": f"File deleted: {filename}"
        }
        
    except Exception as e:
        logger.exception("Error deleting file")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.delete("/index/{filename}")
def delete_document_index(filename: str, user: CurrentUser):
    """Remove the RAG index (collection + topics + DB row) for a single uploaded file.

    The on-disk PDF is preserved; use ``DELETE /uploaded-files/{filename}``
    to delete the file itself.
    """
    rag_service = get_rag_service()
    try:
        with SessionLocal() as db:
            result = rag_service.remove_index(
                filename=filename,
                user_id=str(user.id),
                db_session=db,
            )
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error", "Index not found"))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error removing document index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


# ============================================================================
# QUIZ GENERATION ENDPOINTS
# ============================================================================

@router.post("/generate-quiz", response_model=GenerateQuizResponse, deprecated=True)
def generate_quiz_from_documents(request: GenerateQuizRequest, user: CurrentUser):
    """
    Generate quiz questions from indexed documents using RAG.
    
    **DEPRECATED**: Use POST /async/generate-quiz instead.

    This endpoint:
    1. Retrieves relevant context from indexed documents based on topic(s)
    2. Uses LLM to generate multiple choice questions
    3. Returns formatted quiz with questions, options, and answers
    
    Supports both single topic (legacy) and multiple topics (new).
    
    Args:
        request: Quiz generation request with topic(s) and number of questions
        
    Returns:
        Generated quiz questions with answers
    """
    logger.warning("DEPRECATED sync endpoint /generate-quiz called — migrate to /async/generate-quiz")
    # Handle both single topic and multiple topics
    topics_list = []
    if request.topics and len(request.topics) > 0:
        topics_list = [t.strip() for t in request.topics if t.strip()]
    elif request.topic and request.topic.strip():
        topics_list = [request.topic.strip()]
    
    logger.info(f"Generate quiz request - Topics: {topics_list}, Num questions: {request.num_questions}")
    
    # Validate inputs
    if not topics_list:
        raise HTTPException(status_code=400, detail="At least one topic is required")
    
    if request.num_questions < 1:
        raise HTTPException(status_code=400, detail="Number of questions must be at least 1")
    
    if request.num_questions > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 questions per request")
    
    try:
        rag_service = get_rag_service()
        
        # Check if index has documents and generate quiz
        with SessionLocal() as db:
            stats = rag_service.get_index_stats(user_id=str(user.id), db_session=db)
            if stats.get("total_documents", 0) == 0:
                raise HTTPException(
                    status_code=400, 
                    detail="No documents indexed. Please upload and index documents first."
                )
            
            # Generate quiz with multiple topics support
            result = rag_service.generate_quiz(
                topic=topics_list[0] if len(topics_list) == 1 else None,
                topics=topics_list if len(topics_list) > 1 else None,
                num_questions=request.num_questions,
                difficulty=request.difficulty,
                language=request.language,
                selected_documents=request.selected_documents,
                user_id=str(user.id),
                db_session=db,
            )
        
        if not result.get("success"):
            partial_questions = [
                QuizQuestion(
                    question_number=q.get("question_number", 0),
                    question=q.get("question", ""),
                    options=q.get("options", {}),
                    correct_answer=q.get("correct_answer", ""),
                )
                for q in result.get("questions", [])
            ]
            return GenerateQuizResponse(
                success=result.get("success", False),
                partial=result.get("partial", False),
                error=result.get("error", "Failed to generate quiz"),
                message=result.get("message"),
                questions=partial_questions,
                topic=", ".join(topics_list),
                num_questions_requested=request.num_questions,
                num_questions_generated=len(partial_questions)
            )
        
        # Convert questions to response model
        questions = []
        for q in result.get("questions", []):
            questions.append(QuizQuestion(
                question_number=q.get("question_number", 0),
                question=q.get("question", ""),
                options=q.get("options", {}),
                correct_answer=q.get("correct_answer", ""),
            ))
        
        return GenerateQuizResponse(
            success=True,
            partial=result.get("partial", False),
            questions=questions,
            topic=", ".join(topics_list),
            num_questions_requested=request.num_questions,
            num_questions_generated=len(questions),
            context_used=result.get("context_used"),
            raw_response=result.get("raw_response") if request.language == "vi" else None,
            message=result.get("message"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error generating quiz")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


class ExportQuizRequest(BaseModel):
    """Request model for quiz export"""
    questions: List[QuizQuestion]
    title: str = "Generated Quiz"
    description: str = ""


class SetLLMProviderRequest(BaseModel):
    """Request model for setting LLM provider"""
    provider: str = "groq"
    model: Optional[str] = None  # Optional model override


class LLMProviderResponse(BaseModel):
    """Response model for LLM provider operations"""
    success: bool
    provider: Optional[str] = None
    model: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    connection: Optional[dict] = None


@router.get("/extract-topics", deprecated=True)
def extract_topics_from_documents(user: CurrentUser):
    """
    Extract suggested topics from indexed documents.
    
    **DEPRECATED**: Use POST /async/extract-topics instead.

    This uses LLM to analyze document content and suggest topics
    that can be used for quiz generation.
    
    Returns:
        List of suggested topics with descriptions
    """
    logger.warning("DEPRECATED sync endpoint /extract-topics called — migrate to /async/extract-topics")
    logger.info("Extracting topics from documents")
    
    try:
        rag_service = get_rag_service()
        
        # Check if index has documents
        with SessionLocal() as db:
            stats = rag_service.get_index_stats(user_id=str(user.id), db_session=db)
            if stats.get("total_documents", 0) == 0:
                return {
                    "success": False,
                    "topics": [],
                    "message": "Chưa có tài liệu nào được index"
                }
            
            # Extract topics
            result = rag_service.extract_topics(user_id=str(user.id), db_session=db)
        
        return result
        
    except Exception as e:
        logger.exception("Error extracting topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/export-quiz-qti")
def export_quiz_to_qti(request: ExportQuizRequest, user: CurrentUser):
    """
    Export quiz questions to QTI 2.1 format as a ZIP package.
    
    Args:
        request: Quiz questions and metadata
        
    Returns:
        ZIP file containing QTI XML and manifest
    """
    try:
        rag_service = get_rag_service()
        
        # Convert Pydantic models to dicts
        questions_dict = [q.dict() for q in request.questions]
        
        # Generate QTI XML
        qti_xml = rag_service._quiz_generator.export_to_qti(
            questions=questions_dict,
            title=request.title,
            description=request.description
        )
        
        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        safe_title = request.title.replace(' ', '_').replace('/', '_').replace('\\', '_')
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Add QTI XML file
            zip_file.writestr(f"{safe_title}.xml", qti_xml)
            
            # Add imsmanifest.xml for IMS Content Packaging compliance
            manifest_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="{safe_title}_manifest" xmlns="http://www.imsglobal.org/xsd/imscp_v1p1">
  <metadata>
    <schema>IMS Content</schema>
    <schemaversion>1.1</schemaversion>
  </metadata>
  <organizations/>
  <resources>
    <resource identifier="{safe_title}_resource" type="imsqti_xmlv1p2" href="{safe_title}.xml">
      <file href="{safe_title}.xml"/>
    </resource>
  </resources>
</manifest>'''
            zip_file.writestr("imsmanifest.xml", manifest_xml)
        
        zip_buffer.seek(0)
        
        # Return as downloadable ZIP file
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=quiz_{safe_title}.zip"
            }
        )
        
    except Exception as e:
        logger.exception("Error exporting quiz to QTI")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


# ==================== TOPIC MANAGEMENT ENDPOINTS ====================

@router.get("/document-topics/{filename}")
def get_document_topics(filename: str, user: CurrentUser):
    """
    Get cached topics for a specific indexed document.
    Topics are extracted during indexing, so this is instant (no LLM call).
    """
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.get_document_topics(
                filename, user_id=str(user.id), db_session=db,
            )
        
        if not result.get("success"):
            raise HTTPException(
                status_code=404, 
                detail=result.get("message", f"No topics found for document: {filename}. Please re-index the document.")
            )
        
        # Extract just the topic names for frontend
        topics = result.get("topics", [])
        topic_names = [t.get("name", "") for t in topics if isinstance(t, dict)]
        
        return {
            "success": True,
            "filename": filename,
            "topics": topic_names,
            "count": len(topic_names)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting topics for {filename}")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


class UpdateTopicsRequest(BaseModel):
    """Request model for updating document topics"""
    topics: List[str]


@router.put("/document-topics/{filename}")
def update_document_topics(filename: str, request: UpdateTopicsRequest, user: CurrentUser):
    """
    Update topics for a specific document.
    Allows users to add, remove, or modify topics.
    """
    try:
        rag_service = get_rag_service()
        
        # Convert string topics to dict format
        topics_dict = [{"name": topic, "description": ""} for topic in request.topics if topic.strip()]
        
        with SessionLocal() as db:
            result = rag_service.update_document_topics(
                filename, topics_dict, user_id=str(user.id), db_session=db,
            )
            # Persist DB changes before the session closes; otherwise the
            # transaction is rolled back on context exit and the UI "reverts"
            # to the previous topic count after a refresh.
            if result.get("success"):
                db.commit()
            else:
                db.rollback()

        if not result.get("success"):
            raise HTTPException(
                status_code=404,
                detail=result.get("message", f"Could not update topics for: {filename}")
            )
        
        return {
            "success": True,
            "filename": filename,
            "topics": request.topics,
            "count": len(request.topics),
            "message": result.get("message", "Topics updated successfully")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating topics for {filename}")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/indexed-documents")
def list_indexed_documents(
    user: CurrentUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """
    List indexed documents with their topic counts (paginated).
    """
    try:
        rag_service = get_rag_service()
        with SessionLocal() as db:
            result = rag_service.get_indexed_documents_with_topics(
                user_id=str(user.id), db_session=db,
            )
        documents = result.get("documents", [])
        
        # Format for frontend - use actual filename for topic lookup
        formatted_docs = []
        for doc in documents:
            formatted_docs.append({
                "filename": doc.get("filename", "unknown"),
                "original_filename": doc.get("filename", "unknown"),
                "topic_count": doc.get("topic_count", 0),
                "indexed_at": doc.get("extracted_at", "")
            })
        
        # Paginate
        total = len(formatted_docs)
        offset = (page - 1) * page_size
        formatted_docs = formatted_docs[offset:offset + page_size]
        
        return {
            "success": True,
            "documents": formatted_docs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size if total else 1,
        }
        
    except Exception as e:
        logger.exception("Error listing indexed documents")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


# ============================================================================
# LLM PROVIDER MANAGEMENT ENDPOINTS
# ============================================================================

@router.post("/set-llm", response_model=LLMProviderResponse)
def set_llm_provider(request: SetLLMProviderRequest, admin: AdminUser):
    """
    Set the LLM provider at runtime.
    
    Currently only supports "groq" (Groq Cloud API).
    
    Args:
        request: Provider name and optional model override
        
    Returns:
        Status of the provider switch with connection test results
    """
    logger.info(f"Setting LLM provider: {request.provider}, model: {request.model}")
    
    # Validate provider
    if request.provider.lower() != "groq":
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {request.provider}. Only 'groq' is supported."
        )
    
    try:
        rag_service = get_rag_service()
        result = rag_service.set_llm_provider(
            provider=request.provider.lower(),
            model=request.model
        )
        
        return LLMProviderResponse(
            success=result.get("success", False),
            provider=result.get("provider"),
            model=result.get("model"),
            message=result.get("message"),
            error=result.get("error"),
            connection=result.get("connection")
        )
        
    except Exception as e:
        logger.exception("Error setting LLM provider")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/llm-provider")
def get_llm_provider_info(user: CurrentUser):
    """
    Get current LLM provider information.
    
    Returns:
        Current provider, model, and available providers
    """
    try:
        rag_service = get_rag_service()
        result = rag_service.get_llm_provider_info()
        
        return result
        
    except Exception as e:
        logger.exception("Error getting LLM provider info")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/llm-status")
def check_llm_status(user: CurrentUser):
    """
    Check current LLM provider connection status.
    
    Tests the connection to the current LLM provider
    and returns detailed status information.

    NOTE: result is cached for 30s to avoid hammering Groq with health-check
    pings (which would consume daily token quota and spam the logs).
    """
    import time as _time

    cache = getattr(check_llm_status, "_cache", None)
    if cache and (_time.time() - cache["at"]) < 30:
        return cache["status"]

    try:
        rag_service = get_rag_service()
        status = rag_service.check_llm_status()

        # If singleton key got rate-limited, try pool keys before reporting
        # disconnected so admins/users see the *aggregate* health.
        if (
            isinstance(status, dict)
            and not status.get("connected")
            and status.get("error_type") in ("rate_limit", "authentication")
        ):
            try:
                from backend.database.base import SessionLocal
                from backend.services.groq_key_pool_service import get_pool_keys_sync
                from backend.modules.document_rag.llm_providers import LLMFactory

                with SessionLocal() as db:
                    pool_keys = get_pool_keys_sync(db)
                for key_info in pool_keys:
                    try:
                        probe_llm = LLMFactory.create(groq_api_key=key_info["plain_key"])
                        probe_status = probe_llm.check_connection()
                        if probe_status.get("connected"):
                            probe_status["message"] = (
                                f"Đang dùng key dự phòng: {key_info.get('name', '?')}"
                            )
                            status = probe_status
                            break
                    except Exception:
                        continue
            except Exception as pool_err:
                logger.warning("LLM-status pool probe failed: %s", pool_err)

        check_llm_status._cache = {"at": _time.time(), "status": status}
        return status

    except Exception as e:
        logger.exception("Error checking LLM status")
        return {
            "connected": False,
            "error": "Connection check failed",
            "message": "Không thể kết nối tới LLM provider"
        }


# ============================================================================
# ASYNC JOB ENDPOINTS
# ============================================================================
# These endpoints return immediately with a job_id.
# The actual work is done in background via Celery.
# Poll GET /api/jobs/{job_id} or use SSE at /api/jobs/{job_id}/stream

from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends
from backend.database import get_async_session
from backend.services.job_service import JobService
from backend.database.models.job import JobType
from backend import tasks
from backend.celery_app import apply_async_nonblocking


class AsyncJobResponse(BaseModel):
    """Response for async job endpoints."""
    success: bool
    job_id: str
    message: str
    status_url: str
    stream_url: str


@router.post("/async/build-index", response_model=AsyncJobResponse)
async def async_build_index(
    user: CurrentUser,
    filename: str = Form(...),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Build index asynchronously (non-blocking).
    
    Returns a job_id immediately. Poll /api/jobs/{job_id} for status.
    """
    file_path = get_user_rag_dir(str(user.id)) / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    
    try:
        job_service = JobService(db)
        
        # Create job with idempotency
        job, _created = await job_service.get_or_create_job(
            user_id=user.id,
            job_type=JobType.BUILD_INDEX,
            payload={"filename": filename, "file_path": str(file_path)},
            idempotency_key=f"build_index:{user.id}:{filename}",
        )
        
        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()
        
        # Queue task
        result = await apply_async_nonblocking(
            tasks.rag_tasks.build_index,
            args=[str(job.id), str(file_path)],
            kwargs={"user_id": str(user.id)},
        )
        
        # Update with Celery task ID
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Indexing job queued for {filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queueing build-index job")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/upload-and-index", response_model=AsyncJobResponse)
async def async_upload_and_index(
    user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Upload and index a document asynchronously (non-blocking).
    
    The file is saved synchronously (fast), then indexing runs in background.
    """
    _validate_pdf_upload(file)
    
    try:
        # Save file synchronously (fast)
        user_upload_dir = get_user_rag_dir(str(user.id))
        file_path = user_upload_dir / file.filename
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Reject non-PDF content before queueing the job (avoids wasting a worker slot)
        _assert_pdf_magic_bytes(file_path)
        
        job_service = JobService(db)
        
        # Create job
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.INGEST_DOCUMENT,
            payload={"filename": file.filename, "file_path": str(file_path)},
        )
        
        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()
        
        # Queue task
        result = await apply_async_nonblocking(
            tasks.rag_tasks.ingest_document,
            args=[str(job.id), str(file_path)],
            kwargs={"user_id": str(user.id)},
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Upload complete, indexing queued for {file.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error in async upload-and-index")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/query", response_model=AsyncJobResponse)
async def async_query_documents(
    request: QueryRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Query documents asynchronously (non-blocking).
    
    Use this for long or complex queries.
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.RAG_QUERY,
            payload={
                "question": request.question,
                "k": request.k,
                "return_context": request.return_context,
            },
        )
        
        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()
        
        result = await apply_async_nonblocking(
            tasks.rag_tasks.query_documents,
            args=[str(job.id), request.question],
            kwargs={"k": request.k, "return_context": request.return_context, "user_id": str(user.id)},
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message="Query job queued",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queueing query job")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/generate-quiz", response_model=AsyncJobResponse)
async def async_generate_quiz(
    request: GenerateQuizRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Generate quiz asynchronously (non-blocking).
    
    Quiz generation can take 10-60+ seconds with LLM. This returns immediately.
    """
    # Validate topics
    topics_list = []
    if request.topics and len(request.topics) > 0:
        topics_list = [t.strip() for t in request.topics if t.strip()]
    elif request.topic and request.topic.strip():
        topics_list = [request.topic.strip()]
    
    if not topics_list:
        raise HTTPException(status_code=400, detail="At least one topic is required")
    
    if request.num_questions < 1 or request.num_questions > 50:
        raise HTTPException(status_code=400, detail="Number of questions must be 1-50")
    
    try:
        job_service = JobService(db)
        
        payload = {
            "topics": topics_list,
            "num_questions": request.num_questions,
            "difficulty": request.difficulty,
            "language": request.language,
            "selected_documents": request.selected_documents,
            "user_id": str(user.id),
        }
        quiz_logger.info(f"Route async_generate_quiz: topics={topics_list}, selected_documents={request.selected_documents!r}, user={user.id}")

        # Idempotency: if the user double-clicks "Generate quiz" we want to
        # reuse the in-flight job instead of burning a second Groq quota.
        idem_key = _generate_quiz_idempotency_key(
            scope="doc",
            user_id=str(user.id),
            topics=topics_list,
            num_questions=request.num_questions,
            difficulty=request.difficulty,
            language=request.language,
            selected_documents=request.selected_documents,
        )
        job, created = await job_service.get_or_create_job(
            user_id=user.id,
            job_type=JobType.GENERATE_QUIZ,
            idempotency_key=idem_key,
            payload=payload,
        )
        
        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()
        
        if created:
            result = await apply_async_nonblocking(
                tasks.llm_tasks.generate_quiz,
                args=[str(job.id)],
                kwargs=payload,
            )
            await job_service.set_celery_task_id(job.id, result.id)
            message = f"Quiz generation queued for topics: {', '.join(topics_list)}"
        else:
            logger.info(f"Reusing in-flight quiz job {job.id} for idempotency_key={idem_key[:12]}…")
            message = "Yêu cầu tạo quiz tương tự đang chạy, đang theo dõi job hiện có."
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=message,
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queueing quiz generation")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.post("/async/extract-topics", response_model=AsyncJobResponse)
async def async_extract_topics(
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Extract topics from all indexed documents asynchronously.
    
    This uses LLM to analyze documents and extract key topics.
    """
    try:
        job_service = JobService(db)
        
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.EXTRACT_TOPICS,
            payload={},
        )
        
        # Commit so the task can see the Job row (critical for eager mode)
        await db.commit()
        
        result = await apply_async_nonblocking(
            tasks.rag_tasks.extract_topics,
            args=[str(job.id)],
            kwargs={"user_id": str(user.id)},
        )
        
        await job_service.set_celery_task_id(job.id, result.id)
        
        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message="Topic extraction queued",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
        
    except Exception as e:
        logger.exception("Error queueing topic extraction")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


class ExtractDocumentTopicsRequest(BaseModel):
    """Request body for the per-file async extract-topics endpoint."""
    filename: str


@router.post("/async/document-extract-topics", response_model=AsyncJobResponse)
async def async_extract_document_topics(
    request: ExtractDocumentTopicsRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_async_session),
):
    """Re-extract topics for a single uploaded document, asynchronously.

    Mirrors ``/api/canvas-rag/async/extract-topics`` but for the upload
    pipeline. Heavy work runs in the rag worker; the caller polls the
    returned job for completion.
    """
    try:
        job_service = JobService(db)
        payload = {
            "filename": request.filename,
            "user_id": str(user.id),
        }
        job = await job_service.create_job(
            user_id=user.id,
            job_type=JobType.EXTRACT_TOPICS,
            payload=payload,
        )
        await db.commit()

        result = await apply_async_nonblocking(
            tasks.rag_tasks.extract_topics_for_document,
            args=[str(job.id), request.filename],
            kwargs={"user_id": str(user.id)},
        )
        await job_service.set_celery_task_id(job.id, result.id)

        return AsyncJobResponse(
            success=True,
            job_id=str(job.id),
            message=f"Topic extraction queued for {request.filename}",
            status_url=f"/api/jobs/{job.id}",
            stream_url=f"/api/jobs/{job.id}/stream",
        )
    except Exception:
        logger.exception("Error queueing per-document topic extraction")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")
