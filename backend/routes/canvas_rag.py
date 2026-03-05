"""
Canvas RAG API Routes
=====================
FastAPI routes for Canvas-specific Document RAG features.
Completely separate from uploaded document routes.
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Form, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.auth.dependencies import CurrentUser, AdminUser
from backend.modules.document_rag.canvas_rag_service import get_canvas_rag_service
from backend.database.base import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()


# ===== Request/Response Models =====

class CanvasDownloadRequest(BaseModel):
    """Request to download a file from Canvas"""
    url: str
    filename: str
    course_id: int
    file_id: int


class CanvasIndexRequest(BaseModel):
    """Request to index a downloaded Canvas file"""
    filename: str
    course_id: Optional[int] = None  # Canvas course ID for collection naming


class CanvasExtractTopicsRequest(BaseModel):
    """Request to extract topics from a Canvas file"""
    filename: str
    num_topics: int = 8


class CanvasUpdateTopicsRequest(BaseModel):
    """Request to update topics for a Canvas file"""
    filename: str
    topics: List[str]


class CanvasQueryRequest(BaseModel):
    """Request model for Canvas RAG query"""
    question: str
    k: Optional[int] = 6
    return_context: bool = False


class CanvasGenerateQuizRequest(BaseModel):
    """Request model for quiz generation from Canvas documents"""
    topics: List[str]
    num_questions: int = 5
    difficulty: str = "medium"
    language: str = "vi"
    k: int = 10
    selected_documents: Optional[List[str]] = None


# ===== API Endpoints =====

@router.post("/download")
async def download_canvas_file(
    request: CanvasDownloadRequest,
    user: CurrentUser,
    x_canvas_token: Optional[str] = Header(None),
    x_canvas_base_url: Optional[str] = Header(None)
):
    """
    Download a file from Canvas with MD5 deduplication.
    Files are stored separately from uploaded files.
    Requires Canvas token for authentication.
    """
    logger.info(f"Downloading Canvas file: {request.filename}")
    
    if not x_canvas_token:
        return {
            "success": False,
            "status": "failed",
            "error": "Canvas access token not provided"
        }
    
    service = get_canvas_rag_service()
    result = await service.download_file(
        url=request.url,
        filename=request.filename,
        course_id=request.course_id,
        file_id=request.file_id,
        canvas_token=x_canvas_token,
        user_id=str(user.id)
    )
    
    return result


@router.post("/index")
async def index_canvas_file(request: CanvasIndexRequest, user: CurrentUser):
    """
    Index a downloaded Canvas file.
    Stores in separate ChromaDB collection from uploaded files.
    Uses per-file collections with course_id for proper isolation.
    """
    logger.info(f"Indexing Canvas file: {request.filename}, course_id: {request.course_id}")
    
    service = get_canvas_rag_service()
    
    # Find the file path in per-user directory
    user_dir = service._get_user_dir(str(user.id))
    file_path = user_dir / request.filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filename}")
    
    with SessionLocal() as db:
        result = service.ingest_document(
            file_path=str(file_path),
            course_id=request.course_id,
            user_id=str(user.id),
            db_session=db,
        )
    
    return result


@router.post("/extract-topics")
async def extract_topics_for_canvas_file(request: CanvasExtractTopicsRequest, user: CurrentUser):
    """
    Extract topics from an indexed Canvas file.
    """
    logger.info(f"Extracting topics for Canvas file: {request.filename}")
    
    service = get_canvas_rag_service()
    result = service.extract_topics_for_file(request.filename, request.num_topics, user_id=str(user.id))
    
    return result


@router.get("/topics/{filename}")
async def get_canvas_document_topics(filename: str, user: CurrentUser):
    """
    Get topics for a Canvas document.
    """
    try:
        service = get_canvas_rag_service()
        with SessionLocal() as db:
            return service.get_document_topics(
                filename, user_id=str(user.id), db_session=db,
            )
    except Exception as e:
        logger.exception("Error getting Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.put("/topics")
async def update_canvas_document_topics(request: CanvasUpdateTopicsRequest, user: CurrentUser):
    """
    Update topics for a Canvas document.
    """
    try:
        logger.info(f"Updating topics for Canvas file: {request.filename}")
        
        service = get_canvas_rag_service()
        with SessionLocal() as db:
            result = service.update_document_topics(
                request.filename, request.topics,
                user_id=str(user.id), db_session=db,
            )
        
        return result
    except Exception as e:
        logger.exception("Error updating Canvas document topics")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/files")
async def list_canvas_files(user: CurrentUser):
    """
    List all downloaded Canvas files.
    """
    service = get_canvas_rag_service()
    return service.list_downloaded_files(user_id=str(user.id))


@router.get("/indexed")
async def list_indexed_canvas_documents(user: CurrentUser):
    """
    List all indexed Canvas documents with topics.
    """
    try:
        service = get_canvas_rag_service()
        with SessionLocal() as db:
            return service.list_indexed_documents(
                user_id=str(user.id), db_session=db,
            )
    except Exception as e:
        logger.exception("Error listing indexed Canvas documents")
        raise HTTPException(status_code=500, detail="Đã xảy ra lỗi khi xử lý yêu cầu")


@router.get("/stats")
async def get_canvas_stats(user: CurrentUser):
    """
    Get Canvas index statistics.
    """
    service = get_canvas_rag_service()
    stats = service.get_index_stats(user_id=str(user.id))
    
    return {
        "success": True,
        "stats": stats
    }


@router.post("/query")
async def query_canvas_documents(request: CanvasQueryRequest, user: CurrentUser):
    """
    Query the Canvas document knowledge base.
    """
    logger.info(f"Canvas RAG Query: {request.question}")
    
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.query(
            question=request.question,
            k=request.k,
            return_context=request.return_context,
            user_id=str(user.id),
            db_session=db,
        )
    
    return result


@router.post("/generate-quiz")
async def generate_quiz_from_canvas_documents(request: CanvasGenerateQuizRequest, user: CurrentUser):
    """
    Generate quiz from Canvas documents.
    """
    logger.info(f"Canvas Quiz Generation - Topics: {request.topics}")
    
    if not request.topics:
        raise HTTPException(status_code=400, detail="At least one topic is required")
    
    service = get_canvas_rag_service()
    with SessionLocal() as db:
        result = service.generate_quiz(
            topics=request.topics,
            num_questions=request.num_questions,
            difficulty=request.difficulty,
            language=request.language,
            k=request.k,
            selected_documents=request.selected_documents,
            user_id=str(user.id),
            db_session=db,
        )
    
    return result


@router.post("/reset")
async def reset_canvas_index(admin: AdminUser):
    """
    Reset Canvas index (delete all indexed documents and files).
    """
    logger.warning("Resetting Canvas document index")
    
    service = get_canvas_rag_service()
    result = service.reset_index()
    
    return result


@router.delete("/files/{filename}")
async def delete_canvas_file(filename: str, user: CurrentUser):
    """
    Delete a Canvas file and its index data.
    """
    logger.info(f"Deleting Canvas file: {filename}")
    
    service = get_canvas_rag_service()
    result = service.delete_file(filename, user_id=str(user.id))
    
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to delete file"))
    
    return result


@router.delete("/index/{filename}")
async def remove_canvas_file_index(filename: str, user: CurrentUser):
    """
    Remove index for a Canvas file (keep the file).
    """
    logger.info(f"Removing index for Canvas file: {filename}")
    
    service = get_canvas_rag_service()
    result = service.remove_index(filename, user_id=str(user.id))
    
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Failed to remove index"))
    
    return result
