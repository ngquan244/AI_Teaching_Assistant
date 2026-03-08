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
    llm_provider: str = "groq"
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


# ===== Canvas Simulation Schemas =====

class TestStudentCreate(BaseModel):
    """Create a test student on Canvas."""
    name: str = Field(..., description="Display name for the test student")
    email: str = Field(..., description="Email / login (pseudonym)")
    account_id: int = Field(default=1, description="Canvas account ID (default root = 1)")


class TestStudentOut(BaseModel):
    """Read-back of a test student."""
    id: str
    canvas_user_id: int
    display_name: str
    email: str
    status: str
    canvas_domain: str
    current_course_id: Optional[int] = None
    current_enrollment_id: Optional[int] = None
    created_at: datetime


class SimulationAnswerItem(BaseModel):
    """One answer within a simulation request."""
    question_id: int = Field(..., description="Canvas quiz question ID")
    answer: Any = Field(..., description="Answer value — varies by question type")


class SimulationExecuteRequest(BaseModel):
    """Run a single simulation attempt."""
    course_id: int = Field(..., description="Canvas course ID")
    quiz_id: int = Field(..., description="Canvas quiz ID")
    test_student_id: str = Field(..., description="Internal test_student UUID")
    answers: List[SimulationAnswerItem] = Field(..., description="Answers to submit")
    access_code: Optional[str] = Field(None, description="Quiz access code if required")


class SimulationBatchRequest(BaseModel):
    """Run multiple simulation attempts with different answer sets."""
    course_id: int
    quiz_id: int
    test_student_id: str
    answer_sets: List[List[SimulationAnswerItem]] = Field(
        ..., description="Each inner list is one attempt's answers"
    )
    access_code: Optional[str] = None


class SimulationRunOut(BaseModel):
    """Result of one simulation run."""
    id: str
    course_id: int
    quiz_id: int
    test_student_name: Optional[str] = None
    canvas_submission_id: Optional[int] = None
    attempt_number: Optional[int] = None
    score: Optional[float] = None
    kept_score: Optional[float] = None
    points_possible: Optional[float] = None
    status: str
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class SimulationPreCheckResponse(BaseModel):
    """Pre-flight check before running a simulation."""
    success: bool
    course_published: Optional[bool] = None
    quiz_published: Optional[bool] = None
    quiz_type: Optional[str] = None
    allowed_attempts: Optional[int] = None
    ip_filter: Optional[str] = None
    access_code_required: bool = False
    warnings: List[str] = []
    error: Optional[str] = None


# ===== Canvas Results Aggregation Schemas =====

class QuizSubmissionSummary(BaseModel):
    """Summary of one quiz submission."""
    user_id: int
    user_name: Optional[str] = None
    submission_id: int
    attempt: int
    score: Optional[float] = None
    kept_score: Optional[float] = None
    points_possible: Optional[float] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    workflow_state: str


class QuizResultsAggregation(BaseModel):
    """Aggregated statistics for a quiz."""
    quiz_id: int
    quiz_title: str
    points_possible: Optional[float] = None
    total_submissions: int = 0
    graded_count: int = 0
    average_score: Optional[float] = None
    median_score: Optional[float] = None
    max_score: Optional[float] = None
    min_score: Optional[float] = None
    std_dev: Optional[float] = None
    score_distribution: Dict[str, int] = Field(
        default={},
        description="Histogram buckets, e.g. {'0-10': 2, '10-20': 5, ...}"
    )
    submissions: List[QuizSubmissionSummary] = []


class EnrollmentGradeItem(BaseModel):
    """One student's enrollment + grade snapshot."""
    user_id: int
    user_name: Optional[str] = None
    enrollment_id: int
    enrollment_state: str
    current_score: Optional[float] = None
    final_score: Optional[float] = None
    current_grade: Optional[str] = None
    final_grade: Optional[str] = None


class CourseGradesAggregation(BaseModel):
    """Aggregated grades across all students in a course."""
    course_id: int
    course_name: Optional[str] = None
    total_students: int = 0
    average_current_score: Optional[float] = None
    average_final_score: Optional[float] = None
    max_current_score: Optional[float] = None
    min_current_score: Optional[float] = None
    grade_distribution: Dict[str, int] = {}
    enrollments: List[EnrollmentGradeItem] = []


class ResultsExportRequest(BaseModel):
    """Request to export results to Excel."""
    course_id: int
    quiz_id: Optional[int] = None
    format: str = Field(default="xlsx", description="Export format: xlsx | csv")
