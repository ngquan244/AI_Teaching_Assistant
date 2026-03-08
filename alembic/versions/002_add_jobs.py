"""Add jobs and job_events tables for background task tracking

Revision ID: 002_add_jobs
Revises: 001_initial
Create Date: 2026-02-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002_add_jobs'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types for jobs
    job_type_enum = postgresql.ENUM(
        'INGEST_DOCUMENT', 'BUILD_INDEX', 'RAG_QUERY', 'EXTRACT_TOPICS',
        'GENERATE_QUIZ', 'EXPORT_QTI',
        'CANVAS_DOWNLOAD', 'CANVAS_BATCH_DOWNLOAD', 'CANVAS_IMPORT_QTI', 'CANVAS_INDEX_FILE',
        'GRADE_BATCH', 'GRADE_SINGLE', 'GENERATE_REPORT',
        'AGENT_INVOKE',
        'FILE_DOWNLOAD', 'EMAIL_SEND',
        name='job_type',
        create_type=False
    )
    
    job_status_enum = postgresql.ENUM(
        'QUEUED', 'STARTED', 'PROGRESS', 'SUCCEEDED', 'FAILED', 'CANCELED', 'REVOKED',
        name='job_status',
        create_type=False
    )
    
    job_event_level_enum = postgresql.ENUM(
        'DEBUG', 'INFO', 'WARNING', 'ERROR',
        name='job_event_level',
        create_type=False
    )
    
    # Create ENUMs in database
    job_type_enum.create(op.get_bind(), checkfirst=True)
    job_status_enum.create(op.get_bind(), checkfirst=True)
    job_event_level_enum.create(op.get_bind(), checkfirst=True)
    
    # Create jobs table
    op.create_table(
        'jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique job identifier'),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True,
                  comment='User who initiated the job'),
        sa.Column('job_type', job_type_enum, nullable=False,
                  comment='Type of background job'),
        sa.Column('status', job_status_enum, nullable=False, server_default='QUEUED',
                  comment='Current job status'),
        sa.Column('progress_pct', sa.Integer(), nullable=False, server_default='0',
                  comment='Progress percentage (0-100)'),
        sa.Column('current_step', sa.String(255), nullable=True,
                  comment='Description of current step'),
        sa.Column('celery_task_id', sa.String(255), nullable=True,
                  comment='Celery task ID for task control'),
        sa.Column('idempotency_key', sa.String(255), nullable=True, unique=True,
                  comment='Unique key for idempotent job creation'),
        sa.Column('payload_json', postgresql.JSONB(), nullable=True,
                  comment='Request parameters (sanitized, no secrets)'),
        sa.Column('result_json', postgresql.JSONB(), nullable=True,
                  comment='Job result data'),
        sa.Column('error_message', sa.Text(), nullable=True,
                  comment='Error message if job failed'),
        sa.Column('error_stack', sa.Text(), nullable=True,
                  comment='Stack trace if job failed'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0',
                  comment='Number of retry attempts'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='5',
                  comment='Maximum retry attempts'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Job creation timestamp'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When worker started the job'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True,
                  comment='When job completed (success or failure)'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Last update timestamp'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        comment='Background job tracking with durable state'
    )
    
    # Create indexes for jobs table
    op.create_index('ix_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('ix_jobs_job_type', 'jobs', ['job_type'])
    op.create_index('ix_jobs_status', 'jobs', ['status'])
    op.create_index('ix_jobs_celery_task_id', 'jobs', ['celery_task_id'])
    op.create_index('ix_jobs_user_status', 'jobs', ['user_id', 'status'])
    op.create_index('ix_jobs_type_status', 'jobs', ['job_type', 'status'])
    op.create_index('ix_jobs_created_at', 'jobs', ['created_at'])
    
    # Create job_events table
    op.create_table(
        'job_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Unique event identifier'),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='Parent job ID'),
        sa.Column('level', job_event_level_enum, nullable=False, server_default='INFO',
                  comment='Log level'),
        sa.Column('message', sa.Text(), nullable=False,
                  comment='Event message'),
        sa.Column('meta_json', postgresql.JSONB(), nullable=True,
                  comment='Additional event metadata'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('NOW()'),
                  comment='Event timestamp'),
        sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ondelete='CASCADE'),
        comment='Job execution event log'
    )
    
    # Create indexes for job_events table
    op.create_index('ix_job_events_job_id', 'job_events', ['job_id'])
    op.create_index('ix_job_events_created_at', 'job_events', ['created_at'])
    op.create_index('ix_job_events_job_created', 'job_events', ['job_id', 'created_at'])
    
    # Create trigger for jobs.updated_at
    op.execute('''
        CREATE TRIGGER update_jobs_updated_at
        BEFORE UPDATE ON jobs
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    ''')


def downgrade() -> None:
    # Drop trigger
    op.execute('DROP TRIGGER IF EXISTS update_jobs_updated_at ON jobs')
    
    # Drop indexes
    op.drop_index('ix_job_events_job_created')
    op.drop_index('ix_job_events_created_at')
    op.drop_index('ix_job_events_job_id')
    op.drop_index('ix_jobs_created_at')
    op.drop_index('ix_jobs_type_status')
    op.drop_index('ix_jobs_user_status')
    op.drop_index('ix_jobs_celery_task_id')
    op.drop_index('ix_jobs_status')
    op.drop_index('ix_jobs_job_type')
    op.drop_index('ix_jobs_user_id')
    
    # Drop tables
    op.drop_table('job_events')
    op.drop_table('jobs')
    
    # Drop ENUM types
    op.execute('DROP TYPE IF EXISTS job_event_level')
    op.execute('DROP TYPE IF EXISTS job_status')
    op.execute('DROP TYPE IF EXISTS job_type')
