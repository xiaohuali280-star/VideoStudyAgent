"""Task persistence, without executing any study tools."""

import sqlalchemy as sa

from alembic import op

revision = "0002_tasks"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    for name in ("assets", "artifacts"):
        op.create_table(
            name,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.UniqueConstraint("task_id", "kind"),
        )
        op.create_index(f"ix_{name}_task_id", name, ["task_id"])
    op.create_table(
        "task_steps",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])
    op.create_table(
        "cache_entries",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade():
    for name in ("cache_entries", "task_steps", "artifacts", "assets", "tasks"):
        op.drop_table(name)
