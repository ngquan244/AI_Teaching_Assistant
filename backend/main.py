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

from backend.routes import chat, upload, quiz, grading, config as config_routes
from backend.routes import document_rag as document_rag_routes
from backend.routes import canvas as canvas_routes
from backend.routes import canvas_rag as canvas_rag_routes
from backend.routes import jobs as jobs_routes
from backend.auth import auth_router
from backend.config import settings
from backend.core import BaseAPIException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events"""
    # Startup
    logger.info("Starting Teaching Assistant Grader API...")
    logger.info(f"Environment: {'development' if settings.DEBUG else 'production'}")
    
    # Ensure directories exist
    for directory in [settings.QUIZ_DIR, settings.EXPORTS_DIR, settings.DATA_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Teaching Assistant Grader API...")


app = FastAPI(
    title="Teaching Assistant Grader API",
    description="API cho hệ thống chấm điểm bài thi tự động với AI Agent",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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
    logger.error(f"Unexpected error: {exc}", exc_info=True)
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
app.include_router(quiz.router, prefix="/api/quiz", tags=["Quiz"])
app.include_router(grading.router, prefix="/api/grading", tags=["Grading"])
app.include_router(config_routes.router, prefix="/api/config", tags=["Configuration"])
app.include_router(document_rag_routes.router, prefix="/api/document-rag", tags=["Document RAG"])
app.include_router(canvas_routes.router, prefix="/api/canvas", tags=["Canvas LMS"])
app.include_router(canvas_rag_routes.router, prefix="/api/canvas-rag", tags=["Canvas RAG"])
app.include_router(jobs_routes.router, tags=["Jobs"])

# Serve static files (generated quizzes, exports)
app.mount("/static/quizzes", StaticFiles(directory=str(settings.QUIZ_DIR)), name="quizzes")
app.mount("/static/exports", StaticFiles(directory=str(settings.EXPORTS_DIR)), name="exports")


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": "Teaching Assistant Grader API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


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
