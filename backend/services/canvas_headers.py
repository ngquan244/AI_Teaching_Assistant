"""
Canvas Headers Helper
=====================
Utility to extract Canvas connection headers (token + base URL) from
incoming FastAPI requests.  Used by permission middleware and routes.
"""

from typing import Optional, Tuple

from fastapi import Request


def extract_canvas_headers(request: Request) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract Canvas base URL and token from request headers.
    Returns ``(base_url, token)`` — either may be ``None``.
    """
    canvas_base_url = (
        request.headers.get("X-Canvas-Base-Url")
        or request.headers.get("x-canvas-base-url")
    )
    canvas_token = (
        request.headers.get("X-Canvas-Token")
        or request.headers.get("x-canvas-token")
    )
    return canvas_base_url, canvas_token


def require_canvas_headers(request: Request) -> Tuple[str, str]:
    """
    Extract Canvas headers and raise ``401`` if either is missing.
    """
    from fastapi import HTTPException

    base_url, token = extract_canvas_headers(request)
    if not base_url or not token:
        raise HTTPException(
            status_code=401,
            detail="Canvas connection required. Provide X-Canvas-Base-Url and X-Canvas-Token headers.",
        )
    return base_url, token
