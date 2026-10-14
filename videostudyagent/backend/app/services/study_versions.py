"""Explicit compatibility import. Never invoked by API startup or the Worker."""

import json
from uuid import uuid5

from sqlalchemy import select

from app.adapters.grounding import validate_notes, validate_quiz
from app.core.errors import StudyError
from app.db.iteration_models import (
    CourseStateRow,
    NotesRevisionRow,
    OperationRow,
    QuizBatchRow,
    SnapshotRow,
)
from app.db.repository import TaskRepository, now
from app.schemas.common import ErrorInfo
from app.schemas.iteration import (
    CourseStudyState,
    InitialStudyRequest,
    NotesDocumentV11,
    NotesRevision,
    OperationOutput,
    QuizBatch,
    QuizDocumentV11,
    StudyOperation,
    TranscriptSnapshot,
)
from app.schemas.study import NotesDocument, QuizDocument, Transcript
from app.services.storage import ArtifactStore, cache_key


class VersionReader:
    def __init__(self, root):
        self.store = ArtifactStore(root, None)

    def _read(self, record, schemas):
        try:
            payload = json.loads(self.store.verify(record).read_bytes())
            if not isinstance(payload, dict):
                raise ValueError("Version document must be an object")
            version = payload.get("schema_version", "1.0")
            if version != record.document_schema_version or version not in schemas:
                raise ValueError("Unknown or inconsistent version")
            return schemas[version].model_validate(payload)
        except (ValueError, TypeError, OSError) as exc:
            raise StudyError("STORAGE_ERROR", "版本文件无效。", 409, True) from exc

    def transcript(self, record):
        return self._read(record, {"1.0": Transcript})

    def notes(self, record):
        return self._read(record, {"1.0": NotesDocument, "1.1": NotesDocumentV11})

    def quiz(self, record):
        result = self._read(record, {"1.0": QuizDocument, "1.1": QuizDocumentV11})
        if result.question_count != record.question_count or result.difficulty != record.difficulty:
            raise StudyError("STORAGE_ERROR", "自测版本参数不一致。", 409, True)
        return result


class LegacyStudyImporter:
    """Indexes validated old artifacts atomically; originals and Task rows are untouched."""

    def __init__(self, root, repository):
        self.root, self.repository = root, repository

    def import_task(self, task_id):
        legacy = TaskRepository(self.repository.engine)
        task = legacy.get(task_id)
        artifacts = {item.kind: item for item in legacy.artifacts(task_id)}
        store = ArtifactStore(self.root, None)
        valid, documents, skipped = {}, {}, []
        for kind, schema in (
            ("transcript", Transcript),
            ("notes", NotesDocument),
            ("quiz", QuizDocument),
        ):
            if kind not in artifacts:
                continue
            try:
                document = store.read_json(artifacts[kind], schema)
                if kind == "notes":
                    validate_notes(document, documents["transcript"])
                elif kind == "quiz":
                    validate_quiz(
                        document, documents["transcript"], documents["notes"], task.options
                    )
                documents[kind], valid[kind] = document, artifacts[kind]
            except (StudyError, ValueError, KeyError, OSError):
                skipped.append(kind)
        request = InitialStudyRequest()
        operation = StudyOperation(
            id=uuid5(task.id, f"legacy-attempt:{task.attempt}"),
            task_id=task.id,
            request=request,
            request_hash=cache_key(request=request.model_dump(mode="json")),
            idempotency_key=f"legacy:{task.attempt}",
            status=task.status,
            attempt=task.attempt,
            created_at=task.created_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error=task.error,
            legacy_options=task.options,
        )
        if task.status == "running":
            operation.status, operation.finished_at = "failed", now()
            operation.error = ErrorInfo(
                code="WORKER_INTERRUPTED", message="旧执行已中断。", retryable=True
            )
        if task.status == "succeeded" and set(valid) != {"transcript", "notes", "quiz"}:
            operation.status, operation.finished_at = "failed", now()
            operation.error = ErrorInfo(
                code="STORAGE_ERROR", message="旧产物不完整。", retryable=True
            )

        repo = self.repository
        with repo._write() as connection:
            repo._course(connection, task_id)
            previous = connection.scalar(
                select(OperationRow.payload).where(OperationRow.id == str(operation.id))
            )
            if previous:
                return {"operation": StudyOperation.model_validate(previous), "skipped": skipped}
            repo._insert_operation(connection, operation)
            source, notes, batch = None, None, None
            if "transcript" in valid:
                artifact = valid["transcript"]
                source = TranscriptSnapshot(
                    id=uuid5(task.id, "transcript:" + artifact.sha256),
                    task_id=task.id,
                    storage_key=artifact.storage_key,
                    sha256=artifact.sha256,
                    created_at=artifact.created_at,
                )
                old = connection.scalar(
                    select(SnapshotRow.payload).where(
                        SnapshotRow.task_id == str(task.id), SnapshotRow.sha256 == source.sha256
                    )
                )
                if old:
                    source = TranscriptSnapshot.model_validate(old)
                else:
                    repo._immutable(
                        connection,
                        SnapshotRow,
                        TranscriptSnapshot,
                        source,
                        {
                            "id": str(source.id),
                            "task_id": str(task.id),
                            "sha256": source.sha256,
                        },
                    )
            if "notes" in valid and source:
                artifact = valid["notes"]
                notes = NotesRevision(
                    id=uuid5(task.id, "notes:" + source.sha256 + ":" + artifact.sha256),
                    task_id=task.id,
                    transcript_snapshot_id=source.id,
                    status="published",
                    document_schema_version="1.0",
                    storage_key=artifact.storage_key,
                    sha256=artifact.sha256,
                    created_at=artifact.created_at,
                )
                repo._immutable(
                    connection,
                    NotesRevisionRow,
                    NotesRevision,
                    notes,
                    {
                        "id": str(notes.id),
                        "task_id": str(task.id),
                        "status": notes.status,
                        "transcript_snapshot_id": str(source.id),
                        "parent_revision_id": None,
                        "operation_id": None,
                    },
                )
            if "quiz" in valid and source and notes:
                artifact = valid["quiz"]
                batch_id = uuid5(task.id, "quiz:" + source.sha256 + ":" + artifact.sha256)
                old = connection.scalar(
                    select(QuizBatchRow.payload).where(QuizBatchRow.id == str(batch_id))
                )
                if old:
                    batch = QuizBatch.model_validate(old)
                else:
                    sequence = (
                        connection.scalar(
                            select(QuizBatchRow.sequence)
                            .where(QuizBatchRow.task_id == str(task.id))
                            .order_by(QuizBatchRow.sequence.desc())
                            .limit(1)
                        )
                        or 0
                    )
                    batch = QuizBatch(
                        id=batch_id,
                        task_id=task.id,
                        transcript_snapshot_id=source.id,
                        notes_revision_id=notes.id,
                        sequence=sequence + 1,
                        nonce=uuid5(task.id, "nonce:" + source.sha256 + ":" + artifact.sha256),
                        question_count=documents["quiz"].question_count,
                        difficulty=documents["quiz"].difficulty,
                        document_schema_version="1.0",
                        storage_key=artifact.storage_key,
                        sha256=artifact.sha256,
                        created_at=artifact.created_at,
                    )
                    repo._immutable(
                        connection,
                        QuizBatchRow,
                        QuizBatch,
                        batch,
                        {
                            "id": str(batch.id),
                            "task_id": str(task.id),
                            "transcript_snapshot_id": str(source.id),
                            "notes_revision_id": str(notes.id),
                            "operation_id": None,
                            "sequence": batch.sequence,
                            "nonce": str(batch.nonce),
                        },
                    )
            operation.output = OperationOutput(
                transcript_snapshot_id=source.id if source else None,
                notes_revision_id=notes.id if notes else None,
                quiz_batch_id=batch.id if batch else None,
            )
            repo._update_operation(connection, operation)
            existing_state = connection.scalar(
                select(CourseStateRow.task_id).where(CourseStateRow.task_id == str(task.id))
            )
            if not existing_state:
                state = CourseStudyState(
                    task_id=task.id,
                    revision=1,
                    transcript_snapshot_id=operation.output.transcript_snapshot_id,
                    notes_revision_id=operation.output.notes_revision_id,
                    quiz_batch_id=operation.output.quiz_batch_id,
                )
                repo._save_state(connection, state)
        return {"operation": operation, "skipped": skipped}
