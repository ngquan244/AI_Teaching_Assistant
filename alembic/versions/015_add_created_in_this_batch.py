"""Add created_in_this_batch flag to student_import_rows.

Revision ID: 015_add_created_in_this_batch
Revises: 014_add_canvas_student_import
Create Date: 2026-05-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "015_add_created_in_this_batch"
down_revision: Union[str, None] = "014_add_canvas_student_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "student_import_rows",
        sa.Column(
            "created_in_this_batch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("student_import_rows", "created_in_this_batch")
