"""
Chat API routes - AI Agent Chat Interactions
"""
import logging
from fastapi import APIRouter

from backend.auth.dependencies import CurrentUser
from backend.schemas import ChatRequest, ChatResponse, ToolUsage
from backend.services import agent_service
from backend.core.config import settings
from backend.core import Messages, BadRequestException

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/send", response_model=ChatResponse)
def send_message(request: ChatRequest, user: CurrentUser):
    """Send a message to the AI agent and get response"""
    if not request.message.strip():
        raise BadRequestException(Messages.EMPTY_MESSAGE)
    
    # Convert history format
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.history
    ]
    
    # Invoke agent with user context
    result = agent_service.invoke(
        message=request.message,
        history=history,
        model=request.model,
        max_iterations=request.max_iterations,
        user_id=str(user.id),
    )
    
    # Format response
    tools_used = [
        ToolUsage(tool=t.get("tool", ""), args=t.get("args", {}))
        for t in result.get("tools_used", [])
    ]
    
    return ChatResponse(
        response=result.get("response", ""),
        iterations=result.get("iterations", 0),
        tools_used=tools_used,
        success=result.get("success", True)
    )


@router.get("/models")
def get_available_models(user: CurrentUser):
    """Get list of available AI models"""
    return {
        "models": settings.AVAILABLE_MODELS,
        "default": settings.DEFAULT_MODEL,
        "provider": settings.LLM_PROVIDER,
    }


@router.delete("/history")
def clear_history(user: CurrentUser):
    """Clear chat history"""
    return {"message": Messages.HISTORY_CLEARED, "success": True}
