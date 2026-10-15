from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic.config import Config
from sqlalchemy import Engine, delete, insert, select, update

from alembic import command
from app.core.errors import StudyError
from app.core.locking import native_lock
from app.db.models import ArtifactRow, AssetRow, CacheRow, StepRow, TaskRow
from app.db.session import create_database_engine
from app.schemas.common import ErrorInfo
from app.schemas.tasks import (
    Artifact,
    ArtifactSummary,
    CacheEntry,
    InputAsset,
    Task,
    TaskDetail,
    TaskStep,
)


def now():
    return datetime.now(UTC)


def initialize_database(path: Path, *, revision: str = "0002_tasks") -> Engine:
    # Stage 8 is opt-in: existing API/Worker must not migrate a user's live database.
    if revision not in {
        "0002_tasks",
        "0003_study_foundation",
        "0004_video_context",
        "0005_quality_reviews",
        "0006_evidence_index",
        "0007_operation_events",
    }:
        raise ValueError("Unknown schema target")
    engine = create_database_engine(path)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    try:
        with native_lock(path.parent / ".schema.lock", timeout=5).acquire():
            with engine.connect() as connection:
                # Only explicit V3 targets rebuild tables. Existing default never does this.
                rebuilding = revision not in {"0002_tasks", "0003_study_foundation"}
                if rebuilding:
                    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                    connection.commit()
                try:
                    with connection.begin():
                        config.attributes["connection"] = connection
                        command.upgrade(config, revision)
                        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone():
                            raise ValueError("Migration violated source ownership")
                finally:
                    if rebuilding:
                        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                        connection.commit()
    except Exception:
        engine.dispose()
        raise StudyError("STORAGE_ERROR", "数据库初始化未完成，请重试。", 503, True) from None
    return engine


class TaskRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, task: Task, assets: list[InputAsset]):
        with self.engine.begin() as connection:
            connection.execute(
                insert(TaskRow).values(
                    id=str(task.id),
                    status=task.status,
                    created_at=task.created_at.isoformat(),
                    payload=task.model_dump(mode="json"),
                )
            )
            for asset in assets:
                connection.execute(
                    insert(AssetRow).values(
                        id=str(asset.id),
                        task_id=str(task.id),
                        kind=asset.kind,
                        payload=asset.model_dump(mode="json"),
                    )
                )

    def get(self, task_id: UUID | str) -> Task:
        with self.engine.connect() as connection:
            payload = connection.scalar(select(TaskRow.payload).where(TaskRow.id == str(task_id)))
        if payload is None:
            raise StudyError("NOT_FOUND", "未找到该任务。", 404)
        return Task.model_validate(payload)

    def list(self, limit: int, offset: int) -> list[Task]:
        with self.engine.connect() as connection:
            rows = connection.scalars(
                select(TaskRow.payload)
                .order_by(
                    TaskRow.created_at.desc(),
                    TaskRow.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            ).all()
        return [Task.model_validate(row) for row in rows]

    def assets(self, task_id: UUID | str) -> list[InputAsset]:
        with self.engine.connect() as connection:
            rows = connection.scalars(
                select(AssetRow.payload).where(
                    AssetRow.task_id == str(task_id),
                )
            ).all()
        return [InputAsset.model_validate(row) for row in rows]

    def artifacts(self, task_id: UUID | str) -> list[Artifact]:
        with self.engine.connect() as connection:
            rows = connection.scalars(
                select(ArtifactRow.payload).where(
                    ArtifactRow.task_id == str(task_id),
                )
            ).all()
        return [Artifact.model_validate(row) for row in rows]

    def detail(self, task_id: UUID | str) -> TaskDetail:
        task = self.get(task_id)
        with self.engine.connect() as connection:
            rows = connection.scalars(
                select(StepRow.payload)
                .where(
                    StepRow.task_id == str(task_id),
                )
                .order_by(StepRow.attempt, StepRow.id)
            ).all()
        steps = sorted(
            [TaskStep.model_validate(row) for row in rows],
            key=lambda item: (item.attempt, item.sequence or 0, str(item.id)),
        )
        return TaskDetail(
            task=task,
            steps=steps,
            input_kinds=[asset.kind for asset in self.assets(task_id)],
            available_artifacts=[
                ArtifactSummary.model_validate(
                    item.model_dump(include={"id", "task_id", "kind", "created_at"})
                )
                for item in self.artifacts(task_id)
            ],
        )

    def claim_next(self) -> Task | None:
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            row = connection.execute(
                select(TaskRow.id, TaskRow.payload)
                .where(
                    TaskRow.status == "queued",
                )
                .order_by(TaskRow.created_at, TaskRow.id)
                .limit(1)
            ).first()
            if row is None:
                return None
            task = Task.model_validate(row.payload).model_copy(
                update={
                    "status": "running",
                    "started_at": now(),
                    "finished_at": None,
                }
            )
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == row.id)
                .values(
                    status=task.status,
                    payload=task.model_dump(mode="json"),
                )
            )
        return task

    def retry(self, task_id: UUID | str) -> Task:
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            payload = connection.scalar(select(TaskRow.payload).where(TaskRow.id == str(task_id)))
            if payload is None:
                raise StudyError("NOT_FOUND", "未找到该任务。", 404)
            task = Task.model_validate(payload)
            if task.status != "failed" or not task.error or not task.error.retryable:
                raise StudyError("TASK_NOT_RETRYABLE", "当前任务不能重试。", 409)
            task = task.model_copy(
                update={
                    "status": "queued",
                    "attempt": task.attempt + 1,
                    "error": None,
                    "current_step": None,
                    "started_at": None,
                    "finished_at": None,
                }
            )
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == str(task_id))
                .values(
                    status=task.status,
                    payload=task.model_dump(mode="json"),
                )
            )
        return task

    def invalidate_completed(self, task_id: UUID | str):
        task = self.get(task_id)
        task = task.model_copy(
            update={
                "status": "failed",
                "error": ErrorInfo(
                    code="STORAGE_ERROR",
                    message="学习结果缺失或损坏，可重新处理。",
                    retryable=True,
                ),
            }
        )
        with self.engine.begin() as connection:
            connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == str(task_id),
                    TaskRow.status == "succeeded",
                )
                .values(status="failed", payload=task.model_dump(mode="json"))
            )

    def finish(self, task_id: UUID | str, error: ErrorInfo | None = None):
        task = self.get(task_id)
        task = task.model_copy(
            update={
                "status": "failed" if error else "succeeded",
                "error": error,
                "finished_at": now(),
            }
        )
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == str(task_id),
                    TaskRow.status == "running",
                )
                .values(status=task.status, payload=task.model_dump(mode="json"))
            ).rowcount
        if changed != 1:
            raise StudyError("TASK_STATE_CONFLICT", "任务状态已变化。", 409)

    def save_step(self, step: TaskStep):
        with self.engine.begin() as connection:
            connection.execute(delete(StepRow).where(StepRow.id == str(step.id)))
            connection.execute(
                insert(StepRow).values(
                    id=str(step.id),
                    task_id=str(step.task_id),
                    attempt=step.attempt,
                    payload=step.model_dump(mode="json"),
                )
            )
            if step.tool_name == "unknown":
                return
            payload = connection.scalar(
                select(TaskRow.payload).where(
                    TaskRow.id == str(step.task_id),
                )
            )
            task = Task.model_validate(payload).model_copy(update={"current_step": step.tool_name})
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == str(step.task_id))
                .values(
                    payload=task.model_dump(mode="json"),
                )
            )
            from app.db.event_repository import step_event

            step_event(connection, step)

    def save_artifact(self, artifact: Artifact):
        with self.engine.begin() as connection:
            connection.execute(
                delete(ArtifactRow).where(
                    ArtifactRow.task_id == str(artifact.task_id),
                    ArtifactRow.kind == artifact.kind,
                )
            )
            connection.execute(
                insert(ArtifactRow).values(
                    id=str(artifact.id),
                    task_id=str(artifact.task_id),
                    kind=artifact.kind,
                    payload=artifact.model_dump(mode="json"),
                )
            )

    def get_cache(self, key: str) -> CacheEntry | None:
        with self.engine.connect() as connection:
            value = connection.scalar(select(CacheRow.payload).where(CacheRow.key == key))
        return CacheEntry.model_validate(value) if value else None

    def save_cache(self, entry: CacheEntry):
        with self.engine.begin() as connection:
            connection.execute(delete(CacheRow).where(CacheRow.key == entry.key))
            connection.execute(
                insert(CacheRow).values(
                    key=entry.key,
                    payload=entry.model_dump(mode="json"),
                )
            )

    def recover_interrupted(self):
        for task in self.list(100000, 0):
            if task.status == "running":
                for step in self.detail(task.id).steps:
                    if step.status == "running":
                        step.status, step.finished_at = "failed", now()
                        step.error = ErrorInfo(
                            code="WORKER_INTERRUPTED",
                            message="执行进程中断。",
                            retryable=True,
                            step=step.tool_name,
                        )
                        self.save_step(step)
                self.finish(
                    task.id,
                    ErrorInfo(
                        code="WORKER_INTERRUPTED", message="执行进程中断，请重试。", retryable=True
                    ),
                )
