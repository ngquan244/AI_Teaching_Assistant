"""Add canvas_students, canvas_student_enrollments, student_import_batches, student_import_rows

Revision ID: 014_add_canvas_student_import
Revises: 013_add_course_domain_docs
Create Date: 2026-05-14

Phase-1 production-grade student management tables for the Excel-based
bulk import / enroll flow. Independent of the existing `test_students`
table (which remains reserved for quiz-attempt simulation).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "014_add_canvas_student_import"
down_revision: Union[str, None] = "013_add_course_domain_docs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── canvas_students ────────────────────────────────────────────────
    op.create_table(
        "canvas_students",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canvas_domain", sa.String(255), nullable=False),
        sa.Column("canvas_user_id", sa.Integer, nullable=False),
        sa.Column("student_code", sa.String(32), nullable=True,
                  comment="MSSV — derived from sis_user_id or login_id"),
        sa.Column("sis_user_id", sa.String(64), nullable=True),
        sa.Column("login_id", sa.String(255), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(32), nullable=False,
                  server_default="excel_import",
                  comment="excel_import | synced_from_canvas | manual"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("canvas_domain", "canvas_user_id",
                            name="uq_canvas_students_domain_user"),
        comment="Mirror of Canvas student users for production import/enroll",
    )
    op.create_index("ix_canvas_students_owner_id", "canvas_students", ["owner_id"])
    op.create_index("ix_canvas_students_owner_domain", "canvas_students",
                    ["owner_id", "canvas_domain"])
    op.create_index("ix_canvas_students_email", "canvas_students",
                    ["canvas_domain", "email"])
    # Partial unique on (canvas_domain, student_code) — Postgres only
    op.execute(
        "CREATE UNIQUE INDEX uq_canvas_students_domain_code "
        "ON canvas_students (canvas_domain, student_code) "
        "WHERE student_code IS NOT NULL"
    )

    # ── canvas_student_enrollments ─────────────────────────────────────
    op.create_table(
        "canvas_student_enrollments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("canvas_student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canvas_domain", sa.String(255), nullable=False),
        sa.Column("course_id", sa.Integer, nullable=False),
        sa.Column("canvas_enrollment_id", sa.Integer, nullable=False),
        sa.Column("enrollment_type", sa.String(32), nullable=False,
                  server_default="StudentEnrollment"),
        sa.Column("enrollment_state", sa.String(32), nullable=False,
                  comment="active | invited | inactive | completed | deleted"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["canvas_student_id"], ["canvas_students.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("canvas_domain", "canvas_enrollment_id",
                            name="uq_cse_domain_enrollment"),
    )
    op.create_index("ix_cse_canvas_student_id", "canvas_student_enrollments",
                    ["canvas_student_id"])
    op.create_index("ix_cse_student_course", "canvas_student_enrollments",
                    ["canvas_student_id", "course_id"])
    op.create_index("ix_cse_course_state", "canvas_student_enrollments",
                    ["canvas_domain", "course_id", "enrollment_state"])

    # ── student_import_batches ─────────────────────────────────────────
    op.create_table(
        "student_import_batches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canvas_domain", sa.String(255), nullable=False),
        sa.Column("account_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("course_id", sa.Integer, nullable=True),
        sa.Column("mode", sa.String(20), nullable=False, comment="create | enroll"),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="preview",
                  comment="preview | confirmed | failed | expired"),
        sa.Column("total_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("enroll_after_create", sa.Boolean, nullable=False,
                  server_default=sa.text("false")),
        sa.Column("enroll_existing", sa.Boolean, nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sib_owner_id", "student_import_batches", ["owner_id"])
    op.create_index("ix_sib_owner_status", "student_import_batches",
                    ["owner_id", "status"])
    op.create_index("ix_sib_created_at", "student_import_batches", ["created_at"])

    # ── student_import_rows ────────────────────────────────────────────
    op.create_table(
        "student_import_rows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("student_code", sa.String(32), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("generated_email", sa.String(255), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("canvas_user_id", sa.Integer, nullable=True),
        sa.Column("canvas_enrollment_id", sa.Integer, nullable=True),
        sa.Column("canvas_student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sis_user_id_used", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["batch_id"], ["student_import_batches.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canvas_student_id"], ["canvas_students.id"],
                                ondelete="SET NULL"),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_sir_batch_row"),
    )
    op.create_index("ix_sir_batch_id", "student_import_rows", ["batch_id"])
    op.create_index("ix_sir_batch_status", "student_import_rows",
                    ["batch_id", "status"])


def downgrade() -> None:
    op.drop_table("student_import_rows")
    op.drop_table("student_import_batches")
    op.drop_table("canvas_student_enrollments")
    op.execute("DROP INDEX IF EXISTS uq_canvas_students_domain_code")
    op.drop_table("canvas_students")
