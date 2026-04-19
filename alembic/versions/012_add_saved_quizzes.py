"""Add saved_quizzes and saved_quiz_questions tables

Revision ID: 012_add_saved_quizzes
Revises: 011_add_groq_key_pool
Create Date: 2026-04-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012_add_saved_quizzes"
down_revision: Union[str, None] = "011_add_groq_key_pool"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- saved_quizzes --
    op.create_table(
        "saved_quizzes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("course_id", sa.Integer, nullable=True),
        sa.Column("course_name", sa.String(500), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("difficulty", sa.String(20), nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "source_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tags",
            postgresql.JSONB,
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "question_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_starred",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        comment="Snapshot-based saved quizzes organised by user and course",
    )
    op.create_index(
        "ix_saved_quizzes_user_course",
        "saved_quizzes",
        ["user_id", "course_id"],
    )
    op.create_index(
        "ix_saved_quizzes_user_created",
        "saved_quizzes",
        ["user_id", "created_at"],
    )

    # -- saved_quiz_questions --
    op.create_table(
        "saved_quiz_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "quiz_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("saved_quizzes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_number", sa.Integer, nullable=False),
        sa.Column("question_text", sa.Text, nullable=False),
        sa.Column("options", postgresql.JSONB, nullable=False),
        sa.Column("correct_answer", sa.String(5), nullable=False),
        sa.Column("explanation", sa.Text, nullable=True),
        sa.Column(
            "question_type",
            sa.String(50),
            nullable=False,
            server_default="multiple_choice",
        ),
        sa.Column(
            "points",
            sa.Float,
            nullable=False,
            server_default="1.0",
        ),
        sa.UniqueConstraint(
            "quiz_id",
            "question_number",
            name="uq_saved_quiz_question_num",
        ),
        comment="Individual questions belonging to a saved quiz snapshot",
    )


def downgrade() -> None:
    op.drop_table("saved_quiz_questions")
    op.drop_index("ix_saved_quizzes_user_created", table_name="saved_quizzes")
    op.drop_index("ix_saved_quizzes_user_course", table_name="saved_quizzes")
    op.drop_table("saved_quizzes")
