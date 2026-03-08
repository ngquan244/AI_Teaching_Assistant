"""Add RAG collection and topic tables

Revision ID: 004_add_rag_documents
Revises: 003_add_canvas_simulation
Create Date: 2026-03-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_add_rag_documents'
down_revision: Union[str, None] = '003_add_canvas_simulation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ENUM type ─────────────────────────────────────────────────────
    rag_source_type = postgresql.ENUM(
        'upload', 'canvas',
        name='rag_source_type',
        create_type=False,
    )
    rag_source_type.create(op.get_bind(), checkfirst=True)

    # ── rag_collections ───────────────────────────────────────────────
    op.create_table(
        'rag_collections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique collection entry identifier'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Owner user ID'),
        sa.Column('file_hash', sa.String(64), nullable=False,
                  comment='MD5 hash of the source file'),
        sa.Column('filename', sa.String(500), nullable=False,
                  comment='Original filename'),
        sa.Column('collection_name', sa.String(200), nullable=False,
                  comment='ChromaDB collection name'),
        sa.Column('source', rag_source_type, nullable=False,
                  server_default='upload',
                  comment='Document source: upload or canvas'),
        sa.Column('course_id', sa.Integer(), nullable=True,
                  comment='Canvas course ID (NULL for regular uploads)'),
        sa.Column('chunk_count', sa.Integer(), nullable=False,
                  server_default='0',
                  comment='Number of chunks indexed'),
        sa.Column('is_indexed', sa.Boolean(), nullable=False,
                  server_default='false',
                  comment='Whether indexing is complete'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='When the collection was first created'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Last update timestamp'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'file_hash', 'source',
                            name='uq_rag_user_file_source'),
        comment='Registry of indexed document collections in ChromaDB',
    )
    op.create_index('ix_rag_collections_user_id', 'rag_collections', ['user_id'])
    op.create_index('ix_rag_collections_user_source', 'rag_collections',
                    ['user_id', 'source'])
    op.create_index('ix_rag_collections_file_hash', 'rag_collections', ['file_hash'])
    op.create_index('ix_rag_collections_course_id', 'rag_collections', ['course_id'])

    # ── rag_document_topics ───────────────────────────────────────────
    op.create_table(
        'rag_document_topics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Topic entry identifier'),
        sa.Column('collection_id', postgresql.UUID(as_uuid=True), nullable=False,
                  unique=True,
                  comment='FK to rag_collections — one-to-one'),
        sa.Column('topics', postgresql.JSONB(), nullable=False,
                  server_default='[]',
                  comment='JSON array of topic objects'),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='When topics were extracted'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Last topic update'),
        sa.ForeignKeyConstraint(['collection_id'], ['rag_collections.id'],
                                ondelete='CASCADE'),
        comment='Cached LLM-extracted topics per document collection',
    )
    op.create_index('ix_rag_topics_collection_id', 'rag_document_topics',
                    ['collection_id'])


def downgrade() -> None:
    op.drop_table('rag_document_topics')
    op.drop_table('rag_collections')
    op.execute('DROP TYPE IF EXISTS rag_source_type')
