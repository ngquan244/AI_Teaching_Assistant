"""
Logging utilities for the Teaching Assistant Grader.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from .config import settings


def setup_logger(name: str, log_file: str = None, level=logging.INFO) -> logging.Logger:
    """
    Setup logger with file and console handlers
    
    Args:
        name: Logger name
        log_file: Optional log file name
        level: Logging level
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # Create formatters
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler (if log_file specified)
    if log_file:
        log_path = settings.LOGS_DIR / log_file
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


# Create default loggers
agent_logger = setup_logger(
    'agent',
    f'agent_{datetime.now().strftime("%Y%m%d")}.log'
)

tools_logger = setup_logger(
    'tools',
    f'tools_{datetime.now().strftime("%Y%m%d")}.log'
)

grading_logger = setup_logger(
    'grading',
    f'grading_{datetime.now().strftime("%Y%m%d")}.log'
)

# Quiz debug logger — detailed trace to file, summary to console
quiz_logger = setup_logger(
    'quiz_debug',
    f'quiz_debug_{datetime.now().strftime("%Y%m%d")}.log'
)

# Default logger for general use
logger = setup_logger(
    'app',
    f'app_{datetime.now().strftime("%Y%m%d")}.log'
)
