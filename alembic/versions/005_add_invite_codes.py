"""Add invite codes and app settings

Revision ID: 005_add_invite_codes
Revises: 004_add_rag_documents
Create Date: 2026-03-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_add_invite_codes'
down_revision: Union[str, None] = '004_add_rag_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── app_settings ──────────────────────────────────────────────────
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), primary_key=True,
                  comment='Setting key (e.g. SIGNUP_MODE)'),
        sa.Column('value', postgresql.JSONB(), nullable=False,
                  server_default='null',
                  comment='Setting value as JSON'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Last update timestamp'),
        comment='Runtime application settings (key-value store)',
    )

    # Seed default SIGNUP_MODE setting
    op.execute(
        "INSERT INTO app_settings (key, value, updated_at) "
        "VALUES ('SIGNUP_MODE', '\"open\"', now()) "
        "ON CONFLICT (key) DO NOTHING"
    )

    # ── invite_codes ──────────────────────────────────────────────────
    op.create_table(
        'invite_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique invite code identifier'),
        sa.Column('code_hash', sa.String(128), nullable=False, unique=True,
                  comment='HMAC-SHA256 hash of the invite code'),
        sa.Column('code_prefix', sa.String(6), nullable=False,
                  comment='First 6 chars of plaintext code (for admin display)'),
        sa.Column('label', sa.String(100), nullable=True,
                  comment='Admin label/note'),
        sa.Column('max_uses', sa.Integer(), nullable=True,
                  comment='Max allowed uses (NULL = unlimited)'),
        sa.Column('used_count', sa.Integer(), nullable=False,
                  server_default='0',
                  comment='Number of times this code has been used'),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default='true',
                  comment='Whether this code is currently active'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Expiration timestamp (NULL = never expires)'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='Admin who created this code'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='Last update timestamp'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'],
                                ondelete='SET NULL'),
        comment='Invite codes for controlled user signup',
    )
    op.create_index('ix_invite_codes_code_hash', 'invite_codes', ['code_hash'],
                    unique=True)
    op.create_index('ix_invite_codes_is_active', 'invite_codes', ['is_active'])
    op.create_index('ix_invite_codes_expires_at', 'invite_codes', ['expires_at'])

    # ── invite_code_usages ────────────────────────────────────────────
    op.create_table(
        'invite_code_usages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Usage record identifier'),
        sa.Column('invite_code_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='FK to invite code used'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='User who used this code to sign up'),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment='When the code was used'),
        sa.ForeignKeyConstraint(['invite_code_id'], ['invite_codes.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                ondelete='CASCADE'),
        comment='Tracks invite code usage per user',
    )
    op.create_index('ix_invite_code_usages_code_id', 'invite_code_usages',
                    ['invite_code_id'])
    op.create_index('ix_invite_code_usages_user_id', 'invite_code_usages',
                    ['user_id'])


def downgrade() -> None:
    op.drop_table('invite_code_usages')
    op.drop_table('invite_codes')
    op.drop_table('app_settings')
