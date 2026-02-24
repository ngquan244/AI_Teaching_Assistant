"""
Agent Tools Package
Contains all tools for the Teaching Assistant Grader agent.

Each tool is in its own module for better maintainability and extensibility.
"""

from .base import logger
from .calculator import CalculatorTool
from .exam_summary import ExamResultSummaryTool
from .grading import GradingTool, get_grading_tool
from .document_query import DocumentQueryTool
from .user_guide import UserGuideTool

from langchain.tools import BaseTool
from typing import Optional, List


def get_all_tools(respect_config: bool = True) -> List[BaseTool]:
    """
    Return list of available tools.
    When respect_config=True (default), only tools enabled by admin are returned.
    When respect_config=False, all tools are returned regardless of config.
    """
    all_tools = [
        get_grading_tool(),
        CalculatorTool(),
        ExamResultSummaryTool(),
        DocumentQueryTool(),
        UserGuideTool(),
    ]

    if not respect_config:
        return all_tools

    try:
        from backend.services.tool_config_service import get_enabled_tools
        enabled = get_enabled_tools()
        filtered = [t for t in all_tools if t.name in enabled]
        if len(filtered) < len(all_tools):
            disabled = [t.name for t in all_tools if t.name not in enabled]
            logger.info("Tools disabled by admin config: %s", disabled)
        return filtered
    except Exception as e:
        logger.warning("Could not load tool config, returning all tools: %s", e)
        return all_tools


def get_tool_by_name(tool_name: str) -> Optional[BaseTool]:
    """Get a tool by its name"""
    tools = get_all_tools()
    for tool in tools:
        if tool.name == tool_name:
            return tool
    return None


__all__ = [
    # Tools
    "CalculatorTool",
    "ExamResultSummaryTool",
    "GradingTool",
    "get_grading_tool",
    "DocumentQueryTool",
    "UserGuideTool",
    # Utility functions
    "get_all_tools",
    "get_tool_by_name",
    "logger",
]
