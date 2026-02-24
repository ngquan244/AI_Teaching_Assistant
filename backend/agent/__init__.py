"""
Agent module for the Teaching Assistant Grader.
Contains AI agent, tools, and grading functionality.
"""

# Lazy imports to allow submodules to run without full dependencies
_agent_loaded = False
_ReActAgent = None

def _load_agent():
    global _agent_loaded, _ReActAgent
    if not _agent_loaded:
        from .agent_graph import ReActAgent as _RA
        _ReActAgent = _RA
        _agent_loaded = True
    return _ReActAgent

# These imports are lighter - try them, but don't fail if langchain not available
try:
    from .tools import (
        get_all_tools, 
        get_tool_by_name,
        get_grading_tool,
        CalculatorTool,
        ExamResultSummaryTool,
        GradingTool,
    )
    _tools_available = True
except ImportError:
    _tools_available = False
    # Provide stubs
    def get_all_tools(): return []
    def get_tool_by_name(name): return None
    def get_grading_tool(): return None
    CalculatorTool = None
    ExamResultSummaryTool = None
    GradingTool = None


# Property-like access for ReActAgent
class _AgentModule:
    @property
    def ReActAgent(self):
        return _load_agent()

import sys
_module = sys.modules[__name__]

# Make ReActAgent accessible but lazily loaded
def __getattr__(name):
    if name == "ReActAgent":
        return _load_agent()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ReActAgent",
    "get_all_tools",
    "get_tool_by_name",
    "get_grading_tool",
    "CalculatorTool",
    "ExamResultSummaryTool",
    "GradingTool",
]
