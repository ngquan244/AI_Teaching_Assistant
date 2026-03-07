"""
Logging utilities for the Teaching Assistant Grader.

Architecture
────────────
Each named logger writes **full detail to its own daily file** but keeps
the **console minimal** (WARNING+ by default, INFO for the `app` logger).

Loggers:
  app          – startup, auth, route summaries, milestones  (console: INFO)
  celery       – Celery task lifecycle signals                (console: WARNING)
  canvas       – Canvas API, S3, QTI import, polling          (console: WARNING)
  agent        – Agent graph, LLM calls                       (console: WARNING)
  tools        – Agent tool execution                         (console: WARNING)
  grading      – Grading engine                               (console: WARNING)
  quiz_debug   – Quiz generation pipeline trace               (console: WARNING)
"""
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from .config import settings

_TODAY = datetime.now().strftime("%Y%m%d")

# ── Formatters ────────────────────────────────────────────────────────
_CONSOLE_FMT = logging.Formatter(
    "%(asctime)s %(levelname)-1.1s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logger(
    name: str,
    log_file: str = None,
    *,
    file_level: int = logging.INFO,
    console_level: int = logging.WARNING,
) -> logging.Logger:
    """
    Create a logger with separate console / file verbosity.

    Args:
        name:          Logger name (appears in output).
        log_file:      Daily log filename (stored under settings.LOGS_DIR).
        file_level:    Minimum level written to *file*   (default INFO).
        console_level: Minimum level written to *console* (default WARNING).
    """
    lgr = logging.getLogger(name)
    lgr.setLevel(min(file_level, console_level))  # capture everything needed

    if lgr.handlers:
        return lgr

    # Console — compact, higher threshold
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(_CONSOLE_FMT)
    lgr.addHandler(ch)

    # File — full detail
    if log_file:
        log_path = settings.LOGS_DIR / log_file
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(file_level)
        fh.setFormatter(_FILE_FMT)
        lgr.addHandler(fh)

    return lgr


# ── Suppress noisy third-party loggers ────────────────────────────────
_NOISY_LOGGERS = [
    "chromadb", "chromadb.config", "chromadb.api",
    "httpx", "httpcore",
    "uvicorn.access", "uvicorn.error",
    "huggingface_hub", "transformers",
    "langchain", "langchain_core", "langchain_community",
    "sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool",
    "sentence_transformers",
]
for _name in _NOISY_LOGGERS:
    _lg = logging.getLogger(_name)
    _lg.setLevel(logging.WARNING)
    _lg.propagate = False


# ── Named loggers ────────────────────────────────────────────────────
# app — the only logger that shows INFO on console (startup, milestones)
logger = setup_logger("app", f"app_{_TODAY}.log", console_level=logging.INFO)

celery_logger = setup_logger("celery", f"celery_{_TODAY}.log")
canvas_logger = setup_logger("canvas", f"canvas_{_TODAY}.log")
agent_logger = setup_logger("agent", f"agent_{_TODAY}.log")
tools_logger = setup_logger("tools", f"tools_{_TODAY}.log")
grading_logger = setup_logger("grading", f"grading_{_TODAY}.log")
quiz_logger = setup_logger("quiz_debug", f"quiz_debug_{_TODAY}.log")


# ── Auto-cleanup old log files (> max_days) ───────────────────────────
def cleanup_old_logs(max_days: int = 14) -> int:
    """Delete log files older than *max_days*. Returns count of removed files."""
    cutoff = datetime.now() - timedelta(days=max_days)
    removed = 0
    try:
        for f in settings.LOGS_DIR.glob("*.log"):
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
    except Exception as e:
        logger.warning(f"Log cleanup error: {e}")
    if removed:
        logger.info(f"Cleaned up {removed} log files older than {max_days} days")
    return removed
