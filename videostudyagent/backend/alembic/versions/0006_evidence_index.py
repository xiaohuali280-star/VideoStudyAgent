import sqlalchemy as sa

from alembic import op

revision = "0006_evidence_index"
down_revision = "0005_quality_reviews"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "evidence_index_manifests",
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("snapshot_id", sa.String(), primary_key=True),
        sa.Column("snapshot_type", sa.String(), primary_key=True),
        sa.Column("source_sha256", sa.String(), nullable=False),
        sa.Column("tokenizer_version", sa.String(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
    )
    op.create_table(
        "evidence_documents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("snapshot_type", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("frame_id", sa.String(), nullable=True),
        sa.UniqueConstraint("task_id", "snapshot_id", "snapshot_type", "source_type", "source_id"),
    )
    op.create_index(
        "ix_evidence_documents_scope",
        "evidence_documents",
        ["task_id", "snapshot_id", "snapshot_type"],
    )
    # Optional acceleration: absence of FTS5/trigram must not make authoritative sources unreadable.
    try:
        op.get_bind().exec_driver_sql(
            "CREATE VIRTUAL TABLE evidence_fts USING fts5(raw_text, tokenize='trigram')"
        )
    except sa.exc.OperationalError:
        pass


def downgrade():
    # Only derived indexes are discarded; immutable source snapshots remain authoritative.
    op.get_bind().exec_driver_sql("DROP TABLE IF EXISTS evidence_fts")
    op.drop_table("evidence_documents")
    op.drop_table("evidence_index_manifests")
