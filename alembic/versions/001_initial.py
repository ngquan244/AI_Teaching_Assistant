"""Initial migration - Create users and canvas_tokens tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-02-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types
    user_role_enum = postgresql.ENUM('ADMIN', 'TEACHER', name='user_role', create_type=False)
    user_status_enum = postgresql.ENUM('ACTIVE', 'DISABLED', 'PENDING', name='user_status', create_type=False)
    token_type_enum = postgresql.ENUM('PAT', 'OAUTH', name='token_type', create_type=False)
    
    # Create ENUMs in database
    user_role_enum.create(op.get_bind(), checkfirst=True)
    user_status_enum.create(op.get_bind(), checkfirst=True)
    token_type_enum.create(op.get_bind(), checkfirst=True)
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, 
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique user identifier'),
        sa.Column('email', sa.String(255), nullable=False, unique=True,
                  comment='User email address (unique, used for login)'),
        sa.Column('name', sa.String(255), nullable=False,
                  comment='User display name'),
        sa.Column('role', user_role_enum, nullable=False, server_default='TEACHER',
                  comment='User role for access control'),
        sa.Column('status', user_status_enum, nullable=False, server_default='ACTIVE',
                  comment='Account status'),
        sa.Column('password_hash', sa.String(255), nullable=True,
                  comment='Hashed password (bcrypt/argon2). NULL for OAuth-only users.'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Account creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Last update timestamp'),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Last successful login timestamp'),
        comment='User accounts with role-based access control'
    )
    
    # Create indexes for users table
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_email_status', 'users', ['email', 'status'])
    op.create_index('ix_users_role', 'users', ['role'])
    
    # Create canvas_tokens table
    op.create_table(
        'canvas_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique token identifier'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Owner user ID'),
        sa.Column('canvas_domain', sa.String(255), nullable=False,
                  comment='Canvas LMS domain (e.g., https://canvas.instructure.com)'),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False,
                  comment='AES-256-GCM encrypted access token. NEVER log this value.'),
        sa.Column('token_type', token_type_enum, nullable=False, server_default='PAT',
                  comment='Token type (PAT or OAuth)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Token creation timestamp'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Last API call using this token'),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Revocation timestamp (soft delete)'),
        sa.Column('label', sa.String(100), nullable=True,
                  comment="User-friendly label (e.g., 'Main Canvas Account')"),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        comment='Encrypted Canvas LMS access tokens'
    )
    
    # Create indexes for canvas_tokens table
    op.create_index('ix_canvas_tokens_user_id', 'canvas_tokens', ['user_id'])
    op.create_index('ix_canvas_tokens_user_domain', 'canvas_tokens', ['user_id', 'canvas_domain'])
    op.create_index('ix_canvas_tokens_active', 'canvas_tokens', ['user_id', 'revoked_at'])
    
    # Create trigger for updated_at (PostgreSQL)
    op.execute('''
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    ''')
    
    op.execute('''
        CREATE TRIGGER update_users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    ''')


def downgrade() -> None:
    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS update_users_updated_at ON users')
    op.execute('DROP FUNCTION IF EXISTS update_updated_at_column()')
    
    # Drop indexes
    op.drop_index('ix_canvas_tokens_active')
    op.drop_index('ix_canvas_tokens_user_domain')
    op.drop_index('ix_canvas_tokens_user_id')
    op.drop_index('ix_users_role')
    op.drop_index('ix_users_email_status')
    op.drop_index('ix_users_email')
    
    # Drop tables
    op.drop_table('canvas_tokens')
    op.drop_table('users')
    
    # Drop ENUM types
    op.execute('DROP TYPE IF EXISTS token_type')
    op.execute('DROP TYPE IF EXISTS user_status')
    op.execute('DROP TYPE IF EXISTS user_role')
