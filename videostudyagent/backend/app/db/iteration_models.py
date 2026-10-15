"""Explicit version indexes; legacy artifact rows remain current-result projections."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OperationRow(Base):
    __tablename__ = "study_operations"
    __table_args__ = (
        UniqueConstraint("id", "task_id"),
        UniqueConstraint("task_id", "idempotency_key"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')"),
        CheckConstraint("attempt > 0"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String)
    idempotency_key: Mapped[str] = mapped_column(String)
    request_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class SnapshotRow(Base):
    __tablename__ = "transcript_snapshots"
    __table_args__ = (UniqueConstraint("id", "task_id"), UniqueConstraint("task_id", "sha256"))
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    sha256: Mapped[str] = mapped_column(String)
    payload: Mapped[dict] = mapped_column(JSON)


class PreferencesRow(Base):
    __tablename__ = "note_preferences"
    __table_args__ = (CheckConstraint("revision > 0"),)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)


class NotesRevisionRow(Base):
    __tablename__ = "notes_revisions"
    __table_args__ = (
        CheckConstraint("transcript_snapshot_id IS NOT NULL OR context_snapshot_id IS NOT NULL"),
        UniqueConstraint("id", "task_id"),
        ForeignKeyConstraint(
            ["context_snapshot_id", "task_id"],
            ["video_context_snapshots.id", "video_context_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["transcript_snapshot_id", "task_id"],
            ["transcript_snapshots.id", "transcript_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["parent_revision_id", "task_id"], ["notes_revisions.id", "notes_revisions.task_id"]
        ),
        ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
        CheckConstraint("status IN ('draft','published')"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    transcript_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    context_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class QuizBatchRow(Base):
    __tablename__ = "quiz_batches"
    __table_args__ = (
        CheckConstraint("transcript_snapshot_id IS NOT NULL OR context_snapshot_id IS NOT NULL"),
        UniqueConstraint("id", "task_id"),
        UniqueConstraint("task_id", "sequence"),
        UniqueConstraint("task_id", "nonce"),
        CheckConstraint("sequence > 0"),
        ForeignKeyConstraint(
            ["context_snapshot_id", "task_id"],
            ["video_context_snapshots.id", "video_context_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["transcript_snapshot_id", "task_id"],
            ["transcript_snapshots.id", "transcript_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["notes_revision_id", "task_id"], ["notes_revisions.id", "notes_revisions.task_id"]
        ),
        ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    transcript_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence: Mapped[int] = mapped_column(Integer)
    nonce: Mapped[str] = mapped_column(String)
    context_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class CourseStateRow(Base):
    __tablename__ = "course_study_states"
    __table_args__ = (
        CheckConstraint("revision >= 0"),
        ForeignKeyConstraint(
            ["context_snapshot_id", "task_id"],
            ["video_context_snapshots.id", "video_context_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["transcript_snapshot_id", "task_id"],
            ["transcript_snapshots.id", "transcript_snapshots.task_id"],
        ),
        ForeignKeyConstraint(
            ["notes_revision_id", "task_id"], ["notes_revisions.id", "notes_revisions.task_id"]
        ),
        ForeignKeyConstraint(
            ["quiz_batch_id", "task_id"], ["quiz_batches.id", "quiz_batches.task_id"]
        ),
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    transcript_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes_revision_id: Mapped[str | None] = mapped_column(String, nullable=True)
    quiz_batch_id: Mapped[str | None] = mapped_column(String, nullable=True)
    context_snapshot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ConversationRow(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("id", "task_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class MessageRow(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence"),
        UniqueConstraint("conversation_id", "client_message_id"),
        CheckConstraint("sequence > 0"),
        CheckConstraint("role IN ('user','assistant')"),
        ForeignKeyConstraint(
            ["conversation_id", "task_id"], ["conversations.id", "conversations.task_id"]
        ),
        ForeignKeyConstraint(
            ["notes_revision_id", "task_id"], ["notes_revisions.id", "notes_revisions.task_id"]
        ),
        ForeignKeyConstraint(
            ["operation_id", "task_id"], ["study_operations.id", "study_operations.task_id"]
        ),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String)
    client_message_id: Mapped[str] = mapped_column(String)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String)
    notes_revision_id: Mapped[str] = mapped_column(String)
    operation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


ITERATION_TABLES = (
    "study_operations",
    "transcript_snapshots",
    "note_preferences",
    "notes_revisions",
    "quiz_batches",
    "course_study_states",
    "conversations",
    "conversation_messages",
)
