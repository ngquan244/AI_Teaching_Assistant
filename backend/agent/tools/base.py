"""
Base utilities for agent tools.
Contains shared functionality and common helpers.
"""

import logging
from pathlib import Path
from typing import Callable
from functools import wraps

from ...core.config import settings
from ...core.logger import logger

__all__ = [
    "logger",
]
