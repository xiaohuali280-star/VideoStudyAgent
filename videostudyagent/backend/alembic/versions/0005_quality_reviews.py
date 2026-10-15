import sqlalchemy as sa

from alembic import op

revision = "0005_quality_reviews"
down_revision = "0004_video_context"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "quality_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("target_sha256", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
    )
    for column in ("task_id", "operation_id", "target_sha256"):
        op.create_index(f"ix_quality_reviews_{column}", "quality_reviews", [column])
    op.create_table(
        "review_repairs",
        sa.Column("operation_id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("candidate", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT COUNT(*) FROM quality_reviews")) or connection.scalar(
        sa.text("SELECT COUNT(*) FROM review_repairs")
    ):
        raise RuntimeError("Refusing to discard persisted reviews")
    op.drop_table("review_repairs")
    op.drop_table("quality_reviews")
