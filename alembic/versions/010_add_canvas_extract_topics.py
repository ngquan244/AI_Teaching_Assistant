"""Add CANVAS_EXTRACT_TOPICS to job_type enum

Revision ID: 010_add_canvas_extract_topics
Revises: 009_cleanup_job_types
Create Date: 2025-01-01

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '010_add_canvas_extract_topics'
down_revision: Union[str, None] = '009_cleanup_job_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'CANVAS_EXTRACT_TOPICS'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # The value will remain but be unused after downgrade.
    pass
