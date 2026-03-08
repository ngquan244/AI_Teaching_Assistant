"""
FastAPI Backend for Teaching Assistant Grader
Professional REST API with Clean Architecture
"""
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from backend.routes import chat, upload, grading, config as config_routes
from backend.routes import document_rag as document_rag_routes
from backend.routes import canvas as canvas_routes
from backend.routes import canvas_rag as canvas_rag_routes
from backend.routes import canvas_quiz as canvas_quiz_routes
from backend.routes import canvas_sim as canvas_sim_routes
from backend.routes import canvas_results as canvas_results_routes
from backend.routes import jobs as jobs_routes
from backend.routes import admin as admin_routes
from backend.routes import guide as guide_routes
from backend.auth import auth_router
from backend.core.config import settings
from backend.core import BaseAPIException
from backend.core.logger import logger as app_logger, cleanup_old_logs

# Configure root logger — WARNING+ only so module-level loggers don't spam console.
# Named loggers in backend.core.logger have their own console/file levels.
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-1.1s %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events"""
    # Startup
    app_logger.info("Starting Teaching Assistant Grader API...")
    app_logger.info(f"Environment: {'development' if settings.DEBUG else 'production'}")
    
    # Clean up old log files
    cleanup_old_logs(max_days=14)
    
    # Ensure directories exist
    for directory in [settings.EXPORTS_DIR, settings.DATA_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    
    # ── Preload BAAI/bge-m3 embedding model ──────────────────────────
    try:
        app_logger.info("Preloading embedding model (BAAI/bge-m3)...")
        from backend.modules.document_rag.collection_manager import (
            get_uploads_collection_manager,
            get_canvas_collection_manager,
        )
        get_uploads_collection_manager()
        get_canvas_collection_manager()
        app_logger.info("Embedding model preloaded successfully ✓")
    except Exception as e:
        app_logger.warning(f"Could not preload embedding model (non-fatal): {e}")
    
    # ── Preload RAG & Canvas RAG services ─────────────────────────────
    try:
        app_logger.info("Preloading RAG services...")
        from backend.modules.document_rag.rag_service import RAGService
        from backend.modules.document_rag.canvas_rag_service import CanvasRAGService
        rag = RAGService.get_instance()
        rag._ensure_initialized()
        canvas_rag = CanvasRAGService.get_instance()
        canvas_rag._ensure_initialized()
        app_logger.info("RAG services preloaded successfully ✓")
    except Exception as e:
        app_logger.warning(f"Could not preload RAG services (non-fatal): {e}")
    
    yield
    
    # Shutdown
    app_logger.info("Shutting down Teaching Assistant Grader API...")


# Swagger / ReDoc: only available in development
_is_dev = settings.ENVIRONMENT == "development"

app = FastAPI(
    title="Teaching Assistant Grader API",
    description="API cho hệ thống chấm điểm bài thi tự động với AI Agent",
    version="1.0.0",
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    lifespan=lifespan
)

# CORS configuration for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handlers
@app.exception_handler(BaseAPIException)
async def api_exception_handler(request: Request, exc: BaseAPIException):
    """Handle custom API exceptions"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
            "error_code": exc.error_code
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    app_logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Đã xảy ra lỗi không mong muốn",
            "error_code": "INTERNAL_ERROR"
        }
    )


# Include routers
app.include_router(auth_router, prefix="/api", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
app.include_router(grading.router, prefix="/api/grading", tags=["Grading"])
app.include_router(config_routes.router, prefix="/api/config", tags=["Configuration"])
app.include_router(document_rag_routes.router, prefix="/api/document-rag", tags=["Document RAG"])
app.include_router(canvas_routes.router, prefix="/api/canvas", tags=["Canvas LMS"])
app.include_router(canvas_rag_routes.router, prefix="/api/canvas-rag", tags=["Canvas RAG"])
app.include_router(canvas_quiz_routes.router, prefix="/api/canvas-quiz", tags=["Canvas Quiz"])
app.include_router(canvas_sim_routes.router, prefix="/api/canvas-sim", tags=["Canvas Simulation"])
app.include_router(canvas_results_routes.router, prefix="/api/canvas-results", tags=["Canvas Results"])
app.include_router(jobs_routes.router, tags=["Jobs"])
app.include_router(admin_routes.router, tags=["Admin"])
app.include_router(guide_routes.router, prefix="/api/guide", tags=["Guide"])

# Serve static files (exports)
app.mount("/static/exports", StaticFiles(directory=str(settings.EXPORTS_DIR)), name="exports")

# Serve guide images (uploaded by admin for guide markdown)
app.mount("/media/guide", StaticFiles(directory=str(settings.GUIDE_IMAGES_DIR)), name="guide_media")


@app.get("/")
async def root():
    """API root endpoint"""
    info = {
        "name": "Teaching Assistant Grader API",
        "version": "1.0.0",
        "status": "running",
    }
    if _is_dev:
        info["docs"] = "/docs"
        info["redoc"] = "/redoc"
    return info


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )
