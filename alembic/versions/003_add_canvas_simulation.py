"""Add canvas simulation tables: test_students, simulation_runs, canvas_audit_log

Revision ID: 003_add_canvas_simulation
Revises: 002_add_jobs
Create Date: 2025-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_add_canvas_simulation'
down_revision: Union[str, None] = '002_add_jobs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── ENUM types ────────────────────────────────────────────────────
    test_student_status = postgresql.ENUM(
        'active', 'enrolled', 'unenrolled', 'deleted', 'error',
        name='test_student_status',
        create_type=False,
    )
    simulation_status = postgresql.ENUM(
        'pending', 'enrolling', 'submitting', 'completed', 'partial', 'failed',
        name='simulation_status',
        create_type=False,
    )
    audit_action = postgresql.ENUM(
        'create_user', 'enroll_user', 'unenroll_user',
        'start_submission', 'answer_questions', 'complete_submission',
        'delete_user',
        name='audit_action',
        create_type=False,
    )

    test_student_status.create(op.get_bind(), checkfirst=True)
    simulation_status.create(op.get_bind(), checkfirst=True)
    audit_action.create(op.get_bind(), checkfirst=True)

    # ── test_students ─────────────────────────────────────────────────
    op.create_table(
        'test_students',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()'),
                  comment='Internal PK'),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False,
                  comment='App user who created this test student'),
        sa.Column('canvas_user_id', sa.Integer(), nullable=False, unique=True,
                  comment='User ID on Canvas LMS'),
        sa.Column('canvas_domain', sa.String(255), nullable=False,
                  comment='Canvas domain this student belongs to'),
        sa.Column('display_name', sa.String(255), nullable=False,
                  comment='Name shown in Canvas'),
        sa.Column('email', sa.String(255), nullable=False,
                  comment='Pseudonym unique_id on Canvas'),
        sa.Column('status', test_student_status, nullable=False,
                  server_default='active'),
        sa.Column('current_enrollment_id', sa.Integer(), nullable=True,
                  comment='Most recent Canvas enrollment ID'),
        sa.Column('current_course_id', sa.Integer(), nullable=True,
                  comment='Course the student is currently enrolled in'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        comment='Test student accounts created on Canvas for simulations',
    )
    op.create_index('ix_test_students_owner_id', 'test_students', ['owner_id'])
    op.create_index('ix_test_students_owner_domain', 'test_students', ['owner_id', 'canvas_domain'])

    # ── simulation_runs ───────────────────────────────────────────────
    op.create_table(
        'simulation_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('quiz_id', sa.Integer(), nullable=False),
        sa.Column('test_student_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('canvas_submission_id', sa.Integer(), nullable=True,
                  comment='quiz_submission.id returned by Canvas'),
        sa.Column('attempt_number', sa.Integer(), nullable=True,
                  comment='Attempt number within the quiz'),
        sa.Column('answers_payload', postgresql.JSONB(), nullable=True,
                  comment='Answers sent to Canvas'),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('kept_score', sa.Float(), nullable=True),
        sa.Column('points_possible', sa.Float(), nullable=True),
        sa.Column('status', simulation_status, nullable=False,
                  server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['test_student_id'], ['test_students.id'], ondelete='SET NULL'),
        comment='History of quiz attempt simulations',
    )
    op.create_index('ix_simulation_runs_owner_id', 'simulation_runs', ['owner_id'])
    op.create_index('ix_simulation_runs_owner_quiz', 'simulation_runs', ['owner_id', 'quiz_id'])

    # ── canvas_audit_log ──────────────────────────────────────────────
    op.create_table(
        'canvas_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('action', audit_action, nullable=False),
        sa.Column('simulation_run_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('canvas_domain', sa.String(255), nullable=False),
        sa.Column('canvas_course_id', sa.Integer(), nullable=True),
        sa.Column('canvas_user_id', sa.Integer(), nullable=True),
        sa.Column('canvas_quiz_id', sa.Integer(), nullable=True),
        sa.Column('canvas_submission_id', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('detail', sa.Text(), nullable=True,
                  comment='JSON or free-text detail of the action result'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['simulation_run_id'], ['simulation_runs.id'], ondelete='SET NULL'),
        comment='Immutable audit trail for Canvas mutations',
    )
    op.create_index('ix_audit_log_user_id', 'canvas_audit_log', ['user_id'])
    op.create_index('ix_audit_log_user_action', 'canvas_audit_log', ['user_id', 'action'])
    op.create_index('ix_audit_log_created', 'canvas_audit_log', ['created_at'])


def downgrade() -> None:
    op.drop_table('canvas_audit_log')
    op.drop_table('simulation_runs')
    op.drop_table('test_students')

    # Drop ENUMs
    op.execute('DROP TYPE IF EXISTS audit_action')
    op.execute('DROP TYPE IF EXISTS simulation_status')
    op.execute('DROP TYPE IF EXISTS test_student_status')
