from sqlalchemy import JSON, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OperationEventRow(Base):
    __tablename__ = "operation_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
        UniqueConstraint("operation_id", "state_revision"),
        {"sqlite_autoincrement": True},
    )
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    state_revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


class EventRetentionRow(Base):
    __tablename__ = "event_retention"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    floor: Mapped[int] = mapped_column(Integer)
