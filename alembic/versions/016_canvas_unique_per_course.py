"""Per-course uniqueness for Canvas RAGCollection rows.

The previous unique constraint ``uq_rag_user_file_source`` was
``(user_id, file_hash, source)``. For Canvas files that means the *same*
content uploaded into two different Canvas courses by the same user can
only ever produce **one** ``rag_collections`` row, so the second course
silently overwrites the first one's ``course_id`` / ``collection_name``
(via the existing ``on_conflict_do_update``), and every downstream
lookup / remove / reindex collides between the two courses.

This migration splits the constraint into two partial unique indexes:

* ``uq_rag_user_file_upload``        -- (user_id, file_hash) WHERE source='upload'
* ``uq_rag_user_file_canvas_course`` -- (user_id, file_hash, course_id)
                                        WHERE source='canvas'
                                          AND course_id IS NOT NULL

A third partial index covers the unlikely legacy case of Canvas rows
without a course_id; existing behavior (one row per user+hash) is
preserved for them, which keeps the migration safe to apply on top of
production data without dedupe steps. The application layer is updated
to scope every Canvas read/write by (user_id, course_id, file_hash).

Revision ID: 016_canvas_unique_per_course
Revises: 015_add_created_in_this_batch
Create Date: 2026-05-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "016_canvas_unique_per_course"
down_revision: Union[str, None] = "015_add_created_in_this_batch"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) Drop the old combined unique constraint.
    op.drop_constraint("uq_rag_user_file_source", "rag_collections", type_="unique")

    # 2) Upload rows remain unique per (user_id, file_hash).
    op.create_index(
        "uq_rag_user_file_upload",
        "rag_collections",
        ["user_id", "file_hash"],
        unique=True,
        postgresql_where=sa.text("source = 'upload'"),
    )

    # 3) Canvas rows: unique per (user_id, file_hash, course_id) so the
    #    same file content can be independently indexed in two different
    #    Canvas courses by the same user.
    op.create_index(
        "uq_rag_user_file_canvas_course",
        "rag_collections",
        ["user_id", "file_hash", "course_id"],
        unique=True,
        postgresql_where=sa.text("source = 'canvas' AND course_id IS NOT NULL"),
    )

    # 4) Legacy Canvas rows with NULL course_id (should not occur for new
    #    inserts but may exist in older databases). Keep one-row-per
    #    (user_id, file_hash) for them so re-applying the migration on a
    #    populated DB never raises a duplicate-key error.
    op.create_index(
        "uq_rag_user_file_canvas_legacy",
        "rag_collections",
        ["user_id", "file_hash"],
        unique=True,
        postgresql_where=sa.text("source = 'canvas' AND course_id IS NULL"),
    )


def downgrade() -> None:
    # WARNING: This downgrade will FAIL with a duplicate-key error if any
    # rows were inserted after upgrade() that share (user_id, file_hash)
    # with source='canvas' across different course_id values — exactly
    # the cross-course case that the upgrade was designed to enable. In
    # that situation you must first dedupe Canvas rows manually (delete
    # all but one row per (user_id, file_hash) where source='canvas')
    # before running this downgrade. The fix is intentionally not
    # automated: dropping cross-course rows would silently destroy
    # course-scoped Chroma collection registrations.
    op.drop_index("uq_rag_user_file_canvas_legacy", table_name="rag_collections")
    op.drop_index("uq_rag_user_file_canvas_course", table_name="rag_collections")
    op.drop_index("uq_rag_user_file_upload", table_name="rag_collections")
    op.create_unique_constraint(
        "uq_rag_user_file_source",
        "rag_collections",
        ["user_id", "file_hash", "source"],
    )
