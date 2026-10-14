"""Operation and immutable version indexes. Explicit opt-in during stage 8."""

import sqlalchemy as sa

from alembic import op

revision = "0003_study_foundation"
down_revision = "0002_tasks"
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
    ]


def payload():
    return sa.Column("payload", sa.JSON(), nullable=False)


def owned(column, table):
    return sa.ForeignKeyConstraint([column, "task_id"], [f"{table}.id", f"{table}.task_id"])


def create(name, *columns):
    op.create_table(name, *columns)
    op.create_index(f"ix_{name}_task_id", name, ["task_id"])


def upgrade():
    create(
        "study_operations",
        *common(),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        payload(),
        sa.UniqueConstraint("id", "task_id"),
        sa.UniqueConstraint("task_id", "idempotency_key"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')"),
        sa.CheckConstraint("attempt > 0"),
    )
    op.create_index("ix_study_operations_status", "study_operations", ["status"])
    op.create_index("ix_study_operations_created_at", "study_operations", ["created_at"])
    create(
        "transcript_snapshots",
        *common(),
        sa.Column("sha256", sa.String(), nullable=False),
        payload(),
        sa.UniqueConstraint("id", "task_id"),
        sa.UniqueConstraint("task_id", "sha256"),
    )
    op.create_table(
        "note_preferences",
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        payload(),
        sa.CheckConstraint("revision > 0"),
    )
    create(
        "notes_revisions",
        *common(),
        sa.Column("transcript_snapshot_id", sa.String(), nullable=False),
        sa.Column("parent_revision_id", sa.String(), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        payload(),
        sa.UniqueConstraint("id", "task_id"),
        owned("transcript_snapshot_id", "transcript_snapshots"),
        owned("parent_revision_id", "notes_revisions"),
        owned("operation_id", "study_operations"),
        sa.CheckConstraint("status IN ('draft','published')"),
    )
    create(
        "quiz_batches",
        *common(),
        sa.Column("transcript_snapshot_id", sa.String(), nullable=False),
        sa.Column("notes_revision_id", sa.String(), nullable=True),
        sa.Column("operation_id", sa.String(), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        payload(),
        sa.UniqueConstraint("id", "task_id"),
        sa.UniqueConstraint("task_id", "sequence"),
        sa.UniqueConstraint("task_id", "nonce"),
        sa.CheckConstraint("sequence > 0"),
        owned("transcript_snapshot_id", "transcript_snapshots"),
        owned("notes_revision_id", "notes_revisions"),
        owned("operation_id", "study_operations"),
    )
    op.create_table(
        "course_study_states",
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("transcript_snapshot_id", sa.String(), nullable=True),
        sa.Column("notes_revision_id", sa.String(), nullable=True),
        sa.Column("quiz_batch_id", sa.String(), nullable=True),
        payload(),
        sa.CheckConstraint("revision >= 0"),
        owned("transcript_snapshot_id", "transcript_snapshots"),
        owned("notes_revision_id", "notes_revisions"),
        owned("quiz_batch_id", "quiz_batches"),
    )
    create("conversations", *common(), payload(), sa.UniqueConstraint("id", "task_id"))
    create(
        "conversation_messages",
        *common(),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("client_message_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("notes_revision_id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=True),
        payload(),
        sa.UniqueConstraint("conversation_id", "sequence"),
        sa.UniqueConstraint("conversation_id", "client_message_id"),
        sa.CheckConstraint("sequence > 0"),
        sa.CheckConstraint("role IN ('user','assistant')"),
        owned("conversation_id", "conversations"),
        owned("notes_revision_id", "notes_revisions"),
        owned("operation_id", "study_operations"),
    )


def downgrade():
    names = (
        "conversation_messages",
        "conversations",
        "course_study_states",
        "quiz_batches",
        "notes_revisions",
        "note_preferences",
        "transcript_snapshots",
        "study_operations",
    )
    connection = op.get_bind()
    for name in names:
        if connection.execute(sa.text(f'SELECT COUNT(*) FROM "{name}"')).scalar():
            raise RuntimeError("Refusing to discard non-empty study version indexes")
    for name in names:
        op.drop_table(name)
