"""Add guide documents

Revision ID: 006_add_guide_documents
Revises: 005_add_invite_codes
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006_add_guide_documents'
down_revision: Union[str, None] = '005_add_invite_codes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guide_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique guide document identifier'),
        sa.Column('panel_key', sa.String(50), nullable=False, unique=True,
                  comment='Panel key matching ALL_PANELS'),
        sa.Column('title', sa.String(200), nullable=False,
                  comment='Display title'),
        sa.Column('description', sa.String(500), nullable=True,
                  comment='Short description shown on overview cards'),
        sa.Column('icon_name', sa.String(50), nullable=True,
                  comment='Lucide icon name'),
        sa.Column('content', sa.Text(), nullable=False, server_default='',
                  comment='Markdown content of the guide document'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0',
                  comment='Display order (lower = first)'),
        sa.Column('is_published', sa.Boolean(), nullable=False,
                  server_default=sa.text('true'),
                  comment='Whether this guide is visible to users'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Last update timestamp'),
        comment='Per-panel user guide documents with markdown content',
    )

    op.create_index('ix_guide_documents_panel_key', 'guide_documents', ['panel_key'])
    op.create_index('ix_guide_documents_sort_order', 'guide_documents', ['sort_order'])

    # Seed initial guide documents parsed from user_guide.md
    _seed_guide_documents()


def _seed_guide_documents() -> None:
    """Parse data/user_guide.md and insert one row per ## section."""
    import re
    from pathlib import Path

    guide_file = Path("data/user_guide.md")
    if not guide_file.exists():
        return

    raw = guide_file.read_text(encoding="utf-8")
    parts = re.split(r'^(?=## )', raw, flags=re.MULTILINE)

    # Section title → (panel_key, icon_name, description, sort_order)
    section_map = {
        'chat ai': ('chat', 'MessageSquare', 'Giao tiếp AI bằng ngôn ngữ tự nhiên', 1),
        'upload': ('upload', 'Upload', 'Tải ảnh bài thi lên hệ thống', 2),
        'chấm điểm': ('grading', 'CheckSquare', 'Chấm bài trắc nghiệm tự động', 3),
        'rag tài liệu': ('document_rag', 'BookText', 'Hỏi đáp thông minh từ tài liệu', 4),
        'canvas lms': ('canvas', 'GraduationCap', 'Tích hợp hệ thống Canvas', 5),
        'tạo canvas quiz': ('canvas_quiz', 'PenSquare', 'Tạo & đẩy quiz lên Canvas', 6),
        'cài đặt': ('settings', 'Settings', 'Cấu hình model AI & Canvas', 7),
        'câu hỏi thường gặp': ('faq', 'HelpCircle', 'Giải đáp thắc mắc phổ biến', 8),
    }

    # Extract intro (everything before first ## )
    intro_content = ""
    for part in parts:
        if not part.startswith("## "):
            intro_content = part.strip()
            break

    # Insert overview/intro document
    if intro_content:
        escaped_intro = intro_content.replace("'", "''")
        op.execute(
            "INSERT INTO guide_documents (panel_key, title, description, icon_name, content, sort_order) "
            f"VALUES ('overview', 'Tổng quan', 'Giới thiệu hệ thống TA Grader', 'BookOpen', "
            f"'{escaped_intro}', 0)"
        )

    # Insert one document per section
    for part in parts:
        if not part.startswith("## "):
            continue
        heading_match = re.match(r'^## (.+)$', part, re.MULTILINE)
        if not heading_match:
            continue

        title = heading_match.group(1).strip()
        title_lower = title.lower()
        body = re.sub(r'^## .+\n?', '', part).strip()

        info = section_map.get(title_lower)
        if not info:
            continue

        panel_key, icon_name, description, sort_order = info
        escaped_title = title.replace("'", "''")
        escaped_body = body.replace("'", "''")
        escaped_desc = description.replace("'", "''")

        op.execute(
            "INSERT INTO guide_documents (panel_key, title, description, icon_name, content, sort_order) "
            f"VALUES ('{panel_key}', '{escaped_title}', '{escaped_desc}', "
            f"'{icon_name}', '{escaped_body}', {sort_order}) "
            "ON CONFLICT (panel_key) DO NOTHING"
        )


def downgrade() -> None:
    op.drop_index('ix_guide_documents_sort_order', table_name='guide_documents')
    op.drop_index('ix_guide_documents_panel_key', table_name='guide_documents')
    op.drop_table('guide_documents')
