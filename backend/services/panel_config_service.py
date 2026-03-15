"""
Panel Config Service
====================
Manages which panels/tabs are visible to teachers.
Config is stored as a JSON file in the data/ directory.
"""
import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

# All panel keys (matching frontend TABS constant)
ALL_PANELS = [
    "document_rag",
    "canvas",
    "canvas_quiz",
    "canvas_simulation",
    "canvas_results",
    "guide",
    "settings",
]

# Human-readable labels for each panel
PANEL_LABELS: Dict[str, str] = {
    "document_rag": "Tài Liệu",
    "canvas": "Canvas LMS",
    "canvas_quiz": "Tạo Canvas Quiz",
    "canvas_simulation": "Giả lập Quiz",
    "canvas_results": "Kết quả Canvas",
    "guide": "Hướng dẫn",
    "settings": "Cài đặt",
}

CONFIG_FILE = Path("data/panel_config.json")


def _default_config() -> Dict[str, bool]:
    """All panels enabled by default."""
    return {panel: True for panel in ALL_PANELS}


def get_panel_config() -> Dict[str, bool]:
    """Read panel visibility config from disk. Returns default if file missing."""
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            # Ensure all panels are present (forward-compatible)
            config = _default_config()
            config.update({k: bool(v) for k, v in data.items() if k in ALL_PANELS})
            return config
    except Exception as e:
        logger.warning("Failed to read panel config, using defaults: %s", e)
    return _default_config()


def update_panel_config(updates: Dict[str, bool]) -> Dict[str, bool]:
    """Update panel visibility config. Only accepts known panel keys."""
    config = get_panel_config()

    for key, value in updates.items():
        if key in ALL_PANELS:
            config[key] = bool(value)
        else:
            logger.warning("Ignoring unknown panel key: %s", key)

    # Ensure the data directory exists
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    CONFIG_FILE.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Panel config updated: %s", config)
    return config
