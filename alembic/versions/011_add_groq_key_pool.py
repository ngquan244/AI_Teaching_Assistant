"""Add groq_api_keys table for key pool management

Revision ID: 011_add_groq_key_pool
Revises: 010_add_canvas_extract_topics
Create Date: 2026-04-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_add_groq_key_pool"
down_revision: Union[str, None] = "010_add_canvas_extract_topics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "groq_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("encrypted_key", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        comment="Pool of Groq API keys for quiz generation load distribution",
    )


def downgrade() -> None:
    op.drop_table("groq_api_keys")
