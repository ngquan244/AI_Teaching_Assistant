"""
Guide API Routes
================
Serves the user guide (markdown) for all authenticated users.
Admin can update the guide content.
Sections for hidden panels are automatically stripped for non-admin users.
"""
import logging
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from backend.auth.dependencies import CurrentUser, AdminUser
from backend.database.models.user import UserRole

logger = logging.getLogger(__name__)

router = APIRouter()

GUIDE_FILE = Path("data/user_guide.md")

# Map guide section titles (lowercase) → panel config key
_SECTION_PANEL_MAP = {
    "chat ai": "chat",
    "upload bài thi": "upload",
    "upload": "upload",
    "tạo quiz": "quiz",
    "chấm điểm": "grading",
    "rag tài liệu": "document_rag",
    "canvas lms": "canvas",
    "tạo canvas quiz": "canvas_quiz",
    "cài đặt": "settings",
}

_FEATURE_NAMES = {
    "chat": "Chat AI",
    "upload": "Upload bài thi",
    "quiz": "Tạo Quiz",
    "grading": "Chấm điểm tự động",
    "document_rag": "RAG Tài Liệu",
    "canvas": "Canvas LMS",
    "canvas_quiz": "Tạo Canvas Quiz",
}

# FAQ question keywords → required panel keys (if any panel hidden → hide FAQ)
_FAQ_PANEL_MAP = [
    {"keywords": ["chấm bài thi"], "panels": ["upload", "grading"]},
    {"keywords": ["tài liệu đã upload", "nội dung tài liệu"], "panels": ["document_rag"]},
    {"keywords": ["quiz từ tài liệu", "đẩy lên canvas"], "panels": ["document_rag", "canvas_quiz"]},
    {"keywords": ["tính năng bị khóa"], "panels": ["chat"]},
    {"keywords": ["lỗi khi chấm bài"], "panels": ["grading"]},
    {"keywords": ["ollama", "groq"], "panels": ["settings"]},
]


def _read_guide() -> str:
    """Read the guide markdown file."""
    if not GUIDE_FILE.exists():
        return ""
    return GUIDE_FILE.read_text(encoding="utf-8")


def _filter_guide(raw: str) -> str:
    """Remove guide sections for panels that are hidden by admin."""
    from backend.services.panel_config_service import get_panel_config

    config = get_panel_config()
    hidden = {k for k, v in config.items() if not v}
    if not hidden:
        return raw

    parts = re.split(r'^(?=## )', raw, flags=re.MULTILINE)
    filtered = []

    for part in parts:
        if not part.startswith("## "):
            # Intro — strip hidden feature names from the summary line
            for pk in hidden:
                name = _FEATURE_NAMES.get(pk)
                if name:
                    escaped = re.escape(name)
                    part = re.sub(
                        rf',?\s*\*\*{escaped}\*\*,?',
                        lambda m: ',' if m.group().startswith(',') and m.group().endswith(',') else '',
                        part,
                    )
            part = re.sub(r',\s*,', ',', part)
            part = re.sub(r':\s*,\s*', ': ', part)
            part = re.sub(r',\s*\.', '.', part)
            filtered.append(part)
            continue

        heading_match = re.match(r'^## (.+)$', part, re.MULTILINE)
        if not heading_match:
            filtered.append(part)
            continue

        title = heading_match.group(1).strip().lower()
        panel_key = _SECTION_PANEL_MAP.get(title)
        if panel_key and panel_key in hidden:
            continue

        filtered.append(part)

    result = "".join(filtered)

    # Filter FAQ ### sub-questions inside ## Câu hỏi thường gặp
    def _filter_faq(m: re.Match) -> str:
        faq_block = m.group(0)
        faq_parts = re.split(r'^(?=### )', faq_block, flags=re.MULTILINE)
        kept = []
        for faq in faq_parts:
            if not faq.startswith("### "):
                kept.append(faq)
                continue
            faq_title = (re.match(r'^### (.+)$', faq, re.MULTILINE) or type('', (), {'group': lambda s, i: ''})()).group(1).lower()
            should_hide = False
            for rule in _FAQ_PANEL_MAP:
                if any(kw in faq_title for kw in rule["keywords"]):
                    if any(p in hidden for p in rule["panels"]):
                        should_hide = True
                    break
            if not should_hide:
                kept.append(faq)
        return "".join(kept)

    result = re.sub(r'## Câu hỏi thường gặp[\s\S]*?(?=\n## |$)', _filter_faq, result)

    return result


def _write_guide(content: str) -> None:
    """Write the guide markdown file."""
    GUIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    GUIDE_FILE.write_text(content, encoding="utf-8")


class GuideResponse(BaseModel):
    content: str
    success: bool = True


class GuideUpdateRequest(BaseModel):
    content: str


@router.get("", response_model=GuideResponse)
async def get_guide(user: CurrentUser):
    """Get the user guide content (any authenticated user).
    Non-admin users receive content filtered to only visible panels."""
    content = _read_guide()
    if user.role != UserRole.ADMIN:
        content = _filter_guide(content)
    return GuideResponse(content=content)


@router.put("", response_model=GuideResponse)
async def update_guide(
    request: GuideUpdateRequest,
    _admin: AdminUser,
):
    """Update the user guide content (admin only)."""
    _write_guide(request.content)
    logger.info("User guide updated by admin")
    return GuideResponse(content=request.content)
