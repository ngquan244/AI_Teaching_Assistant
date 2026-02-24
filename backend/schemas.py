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


# ===== Canvas Quiz Schemas =====
class CanvasQuizCreate(BaseModel):
    """Parameters for creating a Canvas quiz."""
    title: str = Field(..., description="Quiz title")
    description: Optional[str] = Field(None, description="Quiz description (HTML supported)")
    quiz_type: str = Field(default="assignment", description="assignment | practice_quiz | graded_survey | survey")
    time_limit: Optional[int] = Field(None, description="Time limit in minutes")
    shuffle_answers: bool = Field(default=True, description="Shuffle answer choices")
    allowed_attempts: int = Field(default=1, description="Number of allowed attempts, -1 for unlimited")
    published: bool = Field(default=False, description="Publish quiz immediately")


class DirectQuizQuestion(BaseModel):
    """A question provided directly by the client (e.g. from AI generation)."""
    question_text: str = Field(..., description="Full question text (HTML okay)")
    question_type: str = Field(default="multiple_choice_question", description="Canvas question type")
    options: Dict[str, str] = Field(..., description='Answer options keyed by letter, e.g. {"A": "text", "B": "text"}')
    correct_keys: List[str] = Field(..., description='Letters of correct option(s), e.g. ["A"]')
    points: float = Field(default=1.0, ge=0, description="Points for this question")


class SourceQuizSelect(BaseModel):
    """Copy specific questions from an existing Canvas quiz."""
    source_quiz_id: int = Field(..., description="Quiz ID to copy questions from")
    question_ids: List[int] = Field(..., description="Question IDs to copy")


class CreateCanvasQuizRequest(BaseModel):
    """Full request to create a Canvas quiz.

    Supports two question sources:
    - direct_questions: questions provided inline (from AI generation / QTI flow)
    - source_questions: questions copied from existing Canvas quizzes
    """
    course_id: int = Field(..., description="Canvas course ID")
    quiz: CanvasQuizCreate
    direct_questions: List[DirectQuizQuestion] = Field(default=[], description="Inline questions to add")
    source_questions: List[SourceQuizSelect] = Field(default=[], description="Copy questions from existing quizzes")
    default_points: float = Field(default=1.0, ge=0, description="Default points for questions")


class CreateCanvasQuizResponse(BaseModel):
    """Response after quiz creation."""
    success: bool
    quiz_id: Optional[int] = None
    quiz_url: Optional[str] = None
    title: Optional[str] = None
    questions_added: int = 0
    groups_created: int = 0
    message: Optional[str] = None
    error: Optional[str] = None
