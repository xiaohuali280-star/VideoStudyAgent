"""Multimodal source indexes; explicit migration only."""

import sqlalchemy as sa

from alembic import op

revision = "0004_video_context"
down_revision = "0003_study_foundation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "video_context_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("transcript_snapshot_id", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("id", "task_id"),
        sa.UniqueConstraint("task_id", "sha256"),
        sa.ForeignKeyConstraint(
            ["transcript_snapshot_id", "task_id"],
            ["transcript_snapshots.id", "transcript_snapshots.task_id"],
        ),
    )
    op.create_index("ix_video_context_snapshots_task_id", "video_context_snapshots", ["task_id"])
    for table in ("notes_revisions", "quiz_batches", "course_study_states"):
        old_check = {
            "notes_revisions": "status IN ('draft','published')",
            "quiz_batches": "sequence > 0",
            "course_study_states": "revision >= 0",
        }[table]
        with op.batch_alter_table(table, table_args=[sa.CheckConstraint(old_check)]) as batch:
            batch.add_column(sa.Column("context_snapshot_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_context",
                "video_context_snapshots",
                ["context_snapshot_id", "task_id"],
                ["id", "task_id"],
            )
            if table != "course_study_states":
                batch.alter_column(
                    "transcript_snapshot_id", existing_type=sa.String(), nullable=True
                )
                batch.create_check_constraint(
                    f"ck_{table}_source",
                    "transcript_snapshot_id IS NOT NULL OR context_snapshot_id IS NOT NULL",
                )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM video_context_snapshots")):
        raise RuntimeError("Refusing lossy context downgrade; restore explicit backup instead")
    for table in ("course_study_states", "quiz_batches", "notes_revisions"):
        old_check = {
            "notes_revisions": "status IN ('draft','published')",
            "quiz_batches": "sequence > 0",
            "course_study_states": "revision >= 0",
        }[table]
        with op.batch_alter_table(table, table_args=[sa.CheckConstraint(old_check)]) as batch:
            batch.drop_constraint(f"fk_{table}_context", type_="foreignkey")
            if table != "course_study_states":
                batch.drop_constraint(f"ck_{table}_source", type_="check")
                batch.alter_column(
                    "transcript_snapshot_id", existing_type=sa.String(), nullable=False
                )
            batch.drop_column("context_snapshot_id")
    op.drop_table("video_context_snapshots")
