"""
Utility functions for the application
"""
import os
import shutil
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Union
from uuid import UUID

logger = logging.getLogger(__name__)


def ensure_directory(path: Union[str, Path]) -> Path:
    """Ensure a directory exists, create if not"""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_directory(path: Union[str, Path], pattern: str = "*") -> int:
    """Clear all files in a directory matching pattern"""
    path = Path(path)
    if not path.exists():
        return 0
    
    count = 0
    for file in path.glob(pattern):
        if file.is_file():
            file.unlink()
            count += 1
    return count


def generate_timestamp_id(prefix: str = "") -> str:
    """Generate a unique ID based on timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if prefix:
        return f"{prefix}_{timestamp}"
    return timestamp


def get_file_extension(filename: str) -> str:
    """Get file extension without dot"""
    return Path(filename).suffix.lstrip(".")


def is_valid_image(filename: str) -> bool:
    """Check if file is a valid image"""
    valid_extensions = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
    return get_file_extension(filename).lower() in valid_extensions


def is_valid_pdf(filename: str) -> bool:
    """Check if file is a valid PDF"""
    return get_file_extension(filename).lower() == "pdf"


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def safe_filename(filename: str) -> str:
    """Make filename safe for filesystem"""
    # Remove or replace unsafe characters
    unsafe_chars = '<>:"/\\|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, "_")
    return filename


def copy_file_safely(src: Union[str, Path], dst: Union[str, Path]) -> Path:
    """Copy file with error handling"""
    src = Path(src)
    dst = Path(dst)
    
    # Ensure destination directory exists
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(src, dst)
    return dst


def list_files(
    directory: Union[str, Path],
    pattern: str = "*",
    recursive: bool = False
) -> List[Path]:
    """List files in directory matching pattern"""
    directory = Path(directory)
    if not directory.exists():
        return []
    
    if recursive:
        return list(directory.rglob(pattern))
    return list(directory.glob(pattern))


def calculate_score(correct: int, total: int, scale: float = 10.0) -> float:
    """Calculate score on a given scale"""
    if total == 0:
        return 0.0
    return round((correct / total) * scale, 2)


def evaluate_score(score: float) -> str:
    """Evaluate score and return assessment"""
    from backend.core.constants import ScoreThresholds, ScoreEvaluation
    
    if score >= ScoreThresholds.EXCELLENT:
        return ScoreEvaluation.EXCELLENT.value
    elif score >= ScoreThresholds.GOOD:
        return ScoreEvaluation.GOOD.value
    elif score >= ScoreThresholds.PASS:
        return ScoreEvaluation.PASS.value
    return ScoreEvaluation.FAIL.value


# =============================================================================
# Per-user workspace helpers
# =============================================================================

def get_user_upload_dir(user_id: Union[str, UUID]) -> Path:
    """
    Get and ensure the per-user upload directory exists.
    
    Args:
        user_id: User UUID (str or UUID)
        
    Returns:
        Path to the user's filled images directory
    """
    from backend.core.config import settings
    path = settings.get_user_filled_dir(str(user_id))
    return ensure_directory(path)


def get_user_result_path(user_id: Union[str, UUID]) -> Path:
    """
    Get the per-user grading result JSON file path.
    Ensures the parent directory exists.
    
    Args:
        user_id: User UUID (str or UUID)
        
    Returns:
        Path to the user's result.json
    """
    from backend.core.config import settings
    path = settings.get_user_result_file(str(user_id))
    ensure_directory(path.parent)
    return path


def get_user_rag_dir(user_id: Union[str, UUID]) -> Path:
    """
    Get and ensure the per-user RAG upload directory exists.

    Args:
        user_id: User UUID (str or UUID)

    Returns:
        Path to the user's RAG upload directory
    """
    from backend.core.config import settings
    path = settings.get_user_rag_upload_dir(str(user_id))
    return ensure_directory(path)


def get_user_canvas_rag_dir(user_id: Union[str, UUID]) -> Path:
    """
    Get and ensure the per-user Canvas RAG directory exists.

    Args:
        user_id: User UUID (str or UUID)

    Returns:
        Path to the user's Canvas RAG directory
    """
    from backend.core.config import settings
    path = settings.get_user_canvas_rag_dir(str(user_id))
    return ensure_directory(path)


def cleanup_user_workspace(user_id: Union[str, UUID]) -> int:
    """
    Delete all files in a user's workspace (filled + results).
    
    Args:
        user_id: User UUID (str or UUID)
        
    Returns:
        Total number of files deleted
    """
    from backend.core.config import settings
    count = 0
    workspace = settings.USER_WORKSPACES_DIR / str(user_id)
    if workspace.exists():
        for item in workspace.rglob("*"):
            if item.is_file():
                item.unlink()
                count += 1
        # Remove empty directories
        for item in sorted(workspace.rglob("*"), reverse=True):
            if item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass
        try:
            workspace.rmdir()
        except OSError:
            pass
    logger.info(f"Cleaned up workspace for user {user_id}: {count} files deleted")
    return count
