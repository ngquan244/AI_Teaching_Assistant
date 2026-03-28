from fastapi import HTTPException
import pytest

from backend.services.url_safety import (
    validate_canvas_origin_url,
    validate_download_url,
)


def test_validate_canvas_origin_url_accepts_public_https_origin():
    assert validate_canvas_origin_url("https://canvas.example.edu") == "https://canvas.example.edu"


@pytest.mark.parametrize(
    "url",
    [
        "http://canvas.example.edu",
        "https://localhost",
        "https://127.0.0.1",
        "https://10.0.0.5",
        "https://canvas.example.edu/path",
        "https://user:pass@canvas.example.edu",
        "https://canvas.example.edu?token=abc",
    ],
)
def test_validate_canvas_origin_url_rejects_unsafe_inputs(url: str):
    with pytest.raises(HTTPException):
        validate_canvas_origin_url(url)


def test_validate_download_url_accepts_signed_https_url():
    url = "https://files.example.edu/download/file.pdf?signature=abc123"
    assert validate_download_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://files.example.edu/download/file.pdf",
        "https://localhost/download/file.pdf",
        "https://127.0.0.1/download/file.pdf",
        "https://192.168.1.10/download/file.pdf",
        "https://user:pass@files.example.edu/download/file.pdf",
        "https://files.example.edu/download/file.pdf#fragment",
    ],
)
def test_validate_download_url_rejects_unsafe_inputs(url: str):
    with pytest.raises(HTTPException):
        validate_download_url(url)
