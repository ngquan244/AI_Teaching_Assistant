"""
Pydantic schemas for API request/response models
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
from datetime import datetime


# ===== Chat Schemas =====
class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message")
    history: List[ChatMessage] = Field(default=[], description="Chat history")
    model: str = Field(default="llama3.1:latest", description="AI model to use")
    max_iterations: int = Field(default=10, description="Max agent iterations")


class ToolUsage(BaseModel):
    tool: str
    args: Dict[str, Any] = {}


class ChatResponse(BaseModel):
    response: str
    iterations: int = 0
    tools_used: List[ToolUsage] = []
    success: bool = True
    error: Optional[str] = None


# ===== Upload Schemas =====
class UploadResponse(BaseModel):
    success: bool
    message: str
    files: List[str] = []
    count: int = 0


# ===== Quiz Schemas =====
class QuizQuestion(BaseModel):
    question: str
    options: Dict[str, str]
    correct: Dict[str, str]


class QuizGenerateRequest(BaseModel):
    num_questions: int = Field(default=10, ge=5, le=30)
    source_pdf: Optional[str] = None


class QuizData(BaseModel):
    id: str
    timestamp: str
    source_pdf: Optional[str] = None
    questions: List[QuizQuestion]
    num_questions: int


class QuizGenerateResponse(BaseModel):
    success: bool
    quiz_id: str
    num_questions: int
    html_file: str
    file_url: str
    message: str


class QuizListResponse(BaseModel):
    quizzes: List[Dict[str, Any]]
    total: int


# ===== Grading Schemas =====
class GradingRequest(BaseModel):
    exam_code: Optional[str] = None


class GradingResult(BaseModel):
    student_id: str
    full_name: str
    email: str
    exam_code: str
    score: float
    evaluation: str


class GradingSummary(BaseModel):
    total_students: int
    average_score: float
    max_score: float
    min_score: float


class GradingResponse(BaseModel):
    success: bool
    exam_code: str
    summary: Optional[GradingSummary] = None
    overall_assessment: Optional[str] = None
    results: List[GradingResult] = []
    excel_file: Optional[str] = None
    error: Optional[str] = None


# ===== Config Schemas =====
class ConfigResponse(BaseModel):
    available_models: List[str]
    default_model: str
    max_iterations: int
    llm_provider: str = "ollama"
    groq_available: bool = False


class ModelConfig(BaseModel):
    model: str
    max_iterations: int = Field(default=10, ge=5, le=20)
