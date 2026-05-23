"""Add course-level domain doc marks and language column

Revision ID: 013_add_course_domain_docs
Revises: 012_add_saved_quizzes
Create Date: 2026-04-19

V1 of course-level shared domain knowledge for quiz generation:
- Adds `rag_collections.language` (detected at index time).
- Creates `canvas_course_domain_docs` table — teachers/admins mark a
  Canvas-indexed file as course-level shared domain knowledge.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013_add_course_domain_docs"
down_revision: Union[str, None] = "012_add_saved_quizzes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- rag_collections.language ----
    op.add_column(
        "rag_collections",
        sa.Column(
            "language",
            sa.String(length=8),
            nullable=True,
            comment="Detected dominant language: 'vi' | 'en' | 'mixed' | NULL",
        ),
    )

    # ---- canvas_course_domain_docs ----
    op.create_table(
        "canvas_course_domain_docs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="Domain mark identifier",
        ),
        sa.Column(
            "course_id",
            sa.Integer,
            nullable=False,
            comment="Canvas course ID this mark applies to",
        ),
        sa.Column(
            "file_hash",
            sa.String(length=64),
            nullable=False,
            comment="MD5 of the file (matches RAGCollection.file_hash)",
        ),
        sa.Column(
            "marked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="User who marked this file as domain knowledge",
        ),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
            comment="False acts as soft-delete (reversible unmark)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "course_id", "file_hash", name="uq_course_domain_doc",
        ),
        comment="Course-level shared domain document marks (V1 RAG)",
    )
    op.create_index(
        "ix_course_domain_docs_course_id",
        "canvas_course_domain_docs",
        ["course_id"],
    )
    op.create_index(
        "ix_course_domain_docs_course_enabled",
        "canvas_course_domain_docs",
        ["course_id", "enabled"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_course_domain_docs_course_enabled",
        table_name="canvas_course_domain_docs",
    )
    op.drop_index(
        "ix_course_domain_docs_course_id",
        table_name="canvas_course_domain_docs",
    )
    op.drop_table("canvas_course_domain_docs")
    op.drop_column("rag_collections", "language")
