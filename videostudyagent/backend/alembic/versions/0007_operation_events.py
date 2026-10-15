import sqlalchemy as sa

from alembic import op

revision = "0007_operation_events"
down_revision = "0006_evidence_index"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "operation_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
        sa.UniqueConstraint("operation_id", "state_revision"),
        sqlite_autoincrement=True,
    )
    for column in ("task_id", "operation_id"):
        op.create_index(f"ix_operation_events_{column}", "operation_events", [column])
    op.create_table(
        "event_retention",
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("floor", sa.Integer(), nullable=False),
    )


def downgrade():
    # Events are derived notifications. Course state/versions/operations remain untouched.
    op.drop_table("event_retention")
    op.drop_table("operation_events")
