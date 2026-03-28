"""
URL safety helpers for basic SSRF hardening.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from fastapi import HTTPException


def _reject(detail: str) -> None:
    raise HTTPException(status_code=400, detail=detail)


def _parse_https_url(url: str):
    if not url or not url.strip():
        _reject("URL is required")

    parsed = urlsplit(url.strip())

    if parsed.scheme.lower() != "https":
        _reject("URL must use HTTPS")

    if not parsed.hostname:
        _reject("URL must include a hostname")

    if parsed.username or parsed.password:
        _reject("URL must not include embedded credentials")

    return parsed


def _reject_unsafe_host(hostname: str) -> None:
    host = hostname.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        _reject("Localhost URLs are not allowed")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        _reject("Private or local network addresses are not allowed")


def validate_canvas_origin_url(url: str) -> str:
    """
    Validate a Canvas origin/base URL.

    Rules:
    - HTTPS only
    - hostname required
    - no embedded credentials
    - no query or fragment
    - path must be empty or "/"
    - localhost/private/reserved IP literals blocked
    """
    parsed = _parse_https_url(url)
    _reject_unsafe_host(parsed.hostname)

    if parsed.query or parsed.fragment:
        _reject("Canvas base URL must not include query parameters or fragments")

    path = parsed.path or ""
    if path not in ("", "/"):
        _reject("Canvas base URL must not include a path")

    if parsed.port is not None:
        return f"https://{parsed.hostname}:{parsed.port}"
    return f"https://{parsed.hostname}"


def validate_download_url(url: str) -> str:
    """
    Validate a signed/download URL.

    Rules:
    - HTTPS only
    - hostname required
    - no embedded credentials
    - allow path and query
    - localhost/private/reserved IP literals blocked
    """
    parsed = _parse_https_url(url)
    _reject_unsafe_host(parsed.hostname)

    if parsed.fragment:
        _reject("Download URL must not include a fragment")

    return parsed.geturl()
