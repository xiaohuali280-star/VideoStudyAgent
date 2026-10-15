from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ContextSnapshotRow(Base):
    __tablename__ = "video_context_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "task_id"),
        UniqueConstraint("task_id", "sha256"),
        ForeignKeyConstraint(
            ["transcript_snapshot_id", "task_id"],
            ["transcript_snapshots.id", "transcript_snapshots.task_id"],
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    transcript_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sha256: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)
