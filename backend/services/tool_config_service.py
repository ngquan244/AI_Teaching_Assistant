"""
Tool Config Service
===================
Manages which agent tools are enabled/disabled by admin.
Config is stored as a JSON file in data/tool_config.json.
Disabled tools are NOT bound to the LLM — the agent literally cannot call them.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All known tools — must match the tool names from agent/tools/
# ---------------------------------------------------------------------------
ALL_TOOLS: List[str] = [
    "execute_notebook",
    "summarize_exam_results",
    "document_query",
    "user_guide",
]

TOOL_LABELS: Dict[str, str] = {
    "execute_notebook": "Chấm bài trắc nghiệm",
    "summarize_exam_results": "Tổng hợp kết quả thi",
    "document_query": "Hỏi đáp tài liệu RAG",
    "user_guide": "Hướng dẫn sử dụng",
}

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "execute_notebook": "Chấm bài trắc nghiệm từ ảnh scan bằng SIFT/OpenCV, phát hiện đáp án, tính điểm và lưu DB.",
    "summarize_exam_results": "Tổng hợp kết quả chấm bài theo mã đề, xuất Excel, gửi email.",
    "document_query": "Truy vấn và trả lời câu hỏi dựa trên tài liệu PDF đã upload vào hệ thống RAG.",
    "user_guide": "Hướng dẫn người dùng sử dụng các tính năng của ứng dụng dựa trên tài liệu hướng dẫn do admin biên soạn.",
}

CONFIG_FILE = Path("data/tool_config.json")


def _default_config() -> Dict[str, Any]:
    """Default config — all tools enabled."""
    return {
        "tools": {tool: True for tool in ALL_TOOLS},
    }


def get_tool_config() -> Dict[str, Any]:
    """Read tool config from JSON file. Returns full config dict."""
    if not CONFIG_FILE.exists():
        config = _default_config()
        _save_config(config)
        return config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # Ensure all tools exist in config (forward compat)
        changed = False
        for tool in ALL_TOOLS:
            if tool not in config.get("tools", {}):
                config.setdefault("tools", {})[tool] = True
                changed = True
        if changed:
            _save_config(config)
        return config
    except Exception as e:
        logger.error(f"Error reading tool config: {e}")
        return _default_config()


def update_tool_config(tools: Dict[str, bool]) -> Dict[str, Any]:
    """Update tool enabled/disabled states. Returns updated config."""
    config = get_tool_config()
    for tool in ALL_TOOLS:
        if tool in tools:
            config["tools"][tool] = bool(tools[tool])
    _save_config(config)
    logger.info(f"Tool config updated: {config['tools']}")
    return config


def get_enabled_tools() -> List[str]:
    """Return list of enabled tool names."""
    config = get_tool_config()
    return [t for t in ALL_TOOLS if config["tools"].get(t, True)]


def is_tool_enabled(tool_name: str) -> bool:
    """Check if a specific tool is enabled."""
    config = get_tool_config()
    return config["tools"].get(tool_name, True)


def _save_config(config: Dict[str, Any]) -> None:
    """Persist config to JSON file."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
