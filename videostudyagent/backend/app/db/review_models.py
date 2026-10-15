from sqlalchemy import JSON, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ReviewRow(Base):
    __tablename__ = "quality_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    target_sha256: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
