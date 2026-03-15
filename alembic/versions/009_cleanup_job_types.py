"""Cleanup job_type enum: remove dead types, rename Canvas types

Remove unused job types (grading, agent, misc) and rename
CANVAS_DOWNLOAD → CANVAS_FILE_DOWNLOAD, CANVAS_IMPORT_QTI → CANVAS_QTI_IMPORT.

Final enum: INGEST_DOCUMENT, BUILD_INDEX, RAG_QUERY, EXTRACT_TOPICS,
GENERATE_QUIZ, CANVAS_FILE_DOWNLOAD, CANVAS_QTI_IMPORT, CANVAS_INDEX_FILE.

Revision ID: 009_cleanup_job_types
Revises: 008_merge_canvas_token_guide
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '009_cleanup_job_types'
down_revision: Union[str, None] = '008_merge_canvas_token_guide'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New enum values (the 8 we keep)
NEW_VALUES = (
    'INGEST_DOCUMENT', 'BUILD_INDEX', 'RAG_QUERY', 'EXTRACT_TOPICS',
    'GENERATE_QUIZ',
    'CANVAS_FILE_DOWNLOAD', 'CANVAS_QTI_IMPORT', 'CANVAS_INDEX_FILE',
)

# Old enum values (all 18 from the original migration + CANVAS_CREATE_QUIZ added later)
OLD_VALUES = (
    'INGEST_DOCUMENT', 'BUILD_INDEX', 'RAG_QUERY', 'EXTRACT_TOPICS',
    'GENERATE_QUIZ', 'EXPORT_QTI',
    'CANVAS_DOWNLOAD', 'CANVAS_BATCH_DOWNLOAD', 'CANVAS_IMPORT_QTI', 'CANVAS_INDEX_FILE',
    'GRADE_BATCH', 'GRADE_SINGLE', 'GENERATE_REPORT',
    'AGENT_INVOKE',
    'CANVAS_CREATE_QUIZ',
    'FILE_DOWNLOAD', 'EMAIL_SEND',
)

# Values being renamed
RENAMES = {
    'CANVAS_DOWNLOAD': 'CANVAS_FILE_DOWNLOAD',
    'CANVAS_IMPORT_QTI': 'CANVAS_QTI_IMPORT',
}

# Values being removed entirely (delete rows with these types)
REMOVED = {
    'EXPORT_QTI', 'CANVAS_BATCH_DOWNLOAD',
    'GRADE_BATCH', 'GRADE_SINGLE', 'GENERATE_REPORT',
    'AGENT_INVOKE', 'CANVAS_CREATE_QUIZ',
    'FILE_DOWNLOAD', 'EMAIL_SEND',
}


def upgrade() -> None:
    # PostgreSQL doesn't support ALTER TYPE ... DROP VALUE or RENAME VALUE (< PG 10).
    # Strategy:
    #   1. Rename old enum type
    #   2. Create new enum type with 8 values
    #   3. Convert column to TEXT (allows updating to new values not in old enum)
    #   4. Rename old values → new names
    #   5. Delete rows with removed job types
    #   6. Convert column to new enum type
    #   7. Drop old enum type

    conn = op.get_bind()

    # 1. Rename old enum so we can create new one with the same name
    conn.execute(sa.text("ALTER TYPE job_type RENAME TO job_type_old"))

    # 2. Create new enum with only the 8 valid values
    new_enum = postgresql.ENUM(*NEW_VALUES, name='job_type', create_type=False)
    new_enum.create(conn, checkfirst=False)

    # 3. Convert column to TEXT (intermediate step to allow renaming values)
    conn.execute(sa.text(
        "ALTER TABLE jobs ALTER COLUMN job_type TYPE TEXT USING job_type::text"
    ))

    # 4. Update renamed values in the now-TEXT column
    for old_val, new_val in RENAMES.items():
        conn.execute(sa.text(
            f"UPDATE jobs SET job_type = '{new_val}' WHERE job_type = '{old_val}'"
        ))

    # 5. Delete rows with removed job types (events first due to FK)
    removed_list = ", ".join(f"'{v}'" for v in REMOVED)
    conn.execute(sa.text(
        f"DELETE FROM job_events WHERE job_id IN "
        f"(SELECT id FROM jobs WHERE job_type IN ({removed_list}))"
    ))
    conn.execute(sa.text(
        f"DELETE FROM jobs WHERE job_type IN ({removed_list})"
    ))

    # 6. Convert column to new enum type
    conn.execute(sa.text(
        "ALTER TABLE jobs ALTER COLUMN job_type TYPE job_type USING job_type::job_type"
    ))

    # 7. Drop old enum
    conn.execute(sa.text("DROP TYPE job_type_old"))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TYPE job_type RENAME TO job_type_new"))

    old_enum = postgresql.ENUM(*OLD_VALUES, name='job_type', create_type=False)
    old_enum.create(conn, checkfirst=False)

    # Convert to TEXT intermediate
    conn.execute(sa.text(
        "ALTER TABLE jobs ALTER COLUMN job_type TYPE TEXT USING job_type::text"
    ))

    # Reverse renames
    for old_val, new_val in RENAMES.items():
        conn.execute(sa.text(
            f"UPDATE jobs SET job_type = '{old_val}' WHERE job_type = '{new_val}'"
        ))

    # Convert back to old enum
    conn.execute(sa.text(
        "ALTER TABLE jobs ALTER COLUMN job_type TYPE job_type USING job_type::job_type"
    ))

    conn.execute(sa.text("DROP TYPE job_type_new"))
