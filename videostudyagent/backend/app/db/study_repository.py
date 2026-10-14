"""Stage 8 persistence foundation. Not consumed by the production Worker yet."""

from contextlib import contextmanager
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import exists, insert, select, update
from sqlalchemy.orm import aliased

from app.core.errors import StudyError
from app.db.iteration_models import (
    ConversationRow,
    CourseStateRow,
    MessageRow,
    NotesRevisionRow,
    OperationRow,
    PreferencesRow,
    QuizBatchRow,
    SnapshotRow,
)
from app.db.models import TaskRow
from app.db.repository import now
from app.schemas.common import ErrorInfo
from app.schemas.iteration import (
    Conversation,
    ConversationMessage,
    CourseNotePreferences,
    CourseStudyState,
    NotePreferences,
    NotesRevision,
    OperationAttempt,
    OperationOutput,
    OperationRequest,
    OperationUsage,
    QuizBatch,
    StudyOperation,
    TranscriptSnapshot,
)
from app.services.storage import cache_key

REQUEST_ADAPTER = TypeAdapter(OperationRequest)


def conflict(message="操作状态或版本已变化。"):
    return StudyError("STUDY_CONFLICT", message, 409)


class StudyRepository:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def _write(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection

    def _course(self, connection, task_id):
        if connection.scalar(select(TaskRow.id).where(TaskRow.id == str(task_id))) is None:
            raise StudyError("NOT_FOUND", "未找到该课程。", 404)

    def _owned(self, connection, row, schema, task_id, item_id):
        payload = connection.scalar(
            select(row.payload).where(row.task_id == str(task_id), row.id == str(item_id))
        )
        if payload is None:
            raise StudyError("NOT_FOUND", "未找到该课程中的记录。", 404)
        return schema.model_validate(payload)

    def _references(self, connection, task_id, request):
        source_id = getattr(request, "transcript_snapshot_id", None)
        if source_id:
            self._owned(connection, SnapshotRow, TranscriptSnapshot, task_id, source_id)
        notes_id = getattr(request, "notes_revision_id", None) or getattr(
            request, "base_revision_id", None
        )
        if notes_id:
            notes = self._owned(connection, NotesRevisionRow, NotesRevision, task_id, notes_id)
            if notes.status != "published":
                raise conflict("操作只能使用已发布的笔记版本。")
            if source_id and notes.transcript_snapshot_id != source_id:
                raise conflict("笔记与字幕版本不匹配。")
        conversation_id = getattr(request, "conversation_id", None)
        if conversation_id:
            self._owned(connection, ConversationRow, Conversation, task_id, conversation_id)

    def enqueue(self, task_id, request, idempotency_key, *, usage=None):
        request = REQUEST_ADAPTER.validate_python(request)
        digest = cache_key(request=request.model_dump(mode="json"))
        operation = StudyOperation(
            id=uuid4(),
            task_id=task_id,
            request=request,
            request_hash=digest,
            idempotency_key=idempotency_key,
            created_at=now(),
            usage=usage or OperationUsage(),
        )
        with self._write() as connection:
            self._course(connection, task_id)
            existing = connection.scalar(
                select(OperationRow.payload).where(
                    OperationRow.task_id == str(task_id),
                    OperationRow.idempotency_key == operation.idempotency_key,
                )
            )
            if existing:
                existing = StudyOperation.model_validate(existing)
                if existing.request_hash != digest:
                    raise conflict("同一幂等键不能用于不同请求。")
                return existing
            self._references(connection, task_id, request)
            self._insert_operation(connection, operation)
        return operation

    def _insert_operation(self, connection, operation):
        connection.execute(
            insert(OperationRow).values(
                id=str(operation.id),
                task_id=str(operation.task_id),
                kind=operation.request.kind,
                idempotency_key=operation.idempotency_key,
                request_hash=operation.request_hash,
                status=operation.status,
                attempt=operation.attempt,
                created_at=operation.created_at.isoformat(),
                payload=operation.model_dump(mode="json"),
            )
        )

    def _update_operation(self, connection, operation):
        connection.execute(
            update(OperationRow)
            .where(OperationRow.id == str(operation.id))
            .values(
                status=operation.status,
                attempt=operation.attempt,
                payload=operation.model_dump(mode="json"),
            )
        )

    def operation(self, task_id, operation_id):
        with self.engine.connect() as connection:
            return self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)

    def operations(self, task_id, limit=20, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        with self.engine.connect() as connection:
            self._course(connection, task_id)
            rows = connection.scalars(
                select(OperationRow.payload)
                .where(OperationRow.task_id == str(task_id))
                .order_by(OperationRow.created_at.desc(), OperationRow.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [StudyOperation.model_validate(row) for row in rows]

    def claim_next(self):
        busy = aliased(OperationRow)
        with self._write() as connection:
            payload = connection.scalar(
                select(OperationRow.payload)
                .where(
                    OperationRow.status == "queued",
                    ~exists(
                        select(busy.id).where(
                            busy.task_id == OperationRow.task_id, busy.status == "running"
                        )
                    ),
                )
                .order_by(OperationRow.created_at, OperationRow.id)
                .limit(1)
            )
            if payload is None:
                return None
            operation = StudyOperation.model_validate(payload).model_copy(
                update={
                    "status": "running",
                    "started_at": now(),
                }
            )
            self._update_operation(connection, operation)
            return operation

    def record_usage(self, task_id, operation_id, usage: OperationUsage):
        usage = OperationUsage.model_validate(usage)
        with self._write() as connection:
            operation = self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            previous = operation.usage
            if operation.status != "running":
                raise conflict()
            if (usage.request_limit, usage.token_limit) != (
                previous.request_limit,
                previous.token_limit,
            ):
                raise conflict("本次尝试的预算不可变更。")
            for key in ("requests_reserved", "tokens_reserved", "input_tokens", "output_tokens"):
                before, after = getattr(previous, key), getattr(usage, key)
                if before is not None and (after is None or after < before):
                    raise conflict("用量记录不能回退。")
            if (
                usage.requests_reserved > usage.request_limit
                or usage.tokens_reserved > usage.token_limit
            ):
                raise conflict("预留用量超过本次预算。")
            operation.usage = usage
            self._update_operation(connection, operation)
            return operation

    def finish(self, task_id, operation_id, *, output=None, error=None):
        output = OperationOutput.model_validate(output or {})
        error = ErrorInfo.model_validate(error) if error is not None else None
        with self._write() as connection:
            operation = self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            if operation.status != "running" or operation.cancel_requested:
                raise conflict()
            if error is None:
                self._validate_output(connection, operation, output)
            operation = operation.model_copy(
                update={
                    "status": "failed" if error else "succeeded",
                    "finished_at": now(),
                    "error": error,
                    "output": output,
                }
            )
            self._update_operation(connection, operation)
            return operation

    def _validate_output(self, connection, operation, output):
        models = {
            "transcript_snapshot_id": (SnapshotRow, TranscriptSnapshot),
            "notes_revision_id": (NotesRevisionRow, NotesRevision),
            "quiz_batch_id": (QuizBatchRow, QuizBatch),
            "message_id": (MessageRow, ConversationMessage),
        }
        documents = {}
        for name, (row, schema) in models.items():
            value = getattr(output, name)
            if value:
                documents[name] = self._owned(connection, row, schema, operation.task_id, value)
        kind = operation.request.kind
        if kind == "initial_study":
            fields = {"transcript_snapshot_id"}
            if operation.request.processing.generate_notes:
                fields.add("notes_revision_id")
            if operation.request.processing.generate_quiz:
                fields.add("quiz_batch_id")
        else:
            fields = {
                {
                    "generate_notes": "notes_revision_id",
                    "generate_quiz": "quiz_batch_id",
                    "revise_notes": "notes_revision_id",
                    "chat_reply": "message_id",
                }[kind]
            }
        if not fields <= documents.keys():
            raise conflict("操作所需结果尚未齐全。")
        allowed = fields if kind == "initial_study" else fields | {"transcript_snapshot_id"}
        if documents.keys() - allowed:
            raise conflict("操作返回了未启用的结果。")
        source_id = output.transcript_snapshot_id or getattr(
            operation.request, "transcript_snapshot_id", None
        )
        for name in ("notes_revision_id", "quiz_batch_id"):
            if (
                name in documents
                and source_id
                and documents[name].transcript_snapshot_id != source_id
            ):
                raise conflict("结果字幕版本不匹配。")
        if "quiz_batch_id" in documents:
            batch = documents["quiz_batch_id"]
            if batch.question_count != 5 or batch.document_schema_version != "1.1":
                raise conflict("新操作必须生成五题新版自测。")
            if (
                kind == "generate_quiz"
                and batch.notes_revision_id != operation.request.notes_revision_id
            ):
                raise conflict("自测使用了不同的笔记版本。")
        if "notes_revision_id" in documents:
            notes = documents["notes_revision_id"]
            if kind == "revise_notes":
                if (
                    notes.parent_revision_id != operation.request.base_revision_id
                    or notes.status != "draft"
                ):
                    raise conflict("修改操作必须返回基于指定版本的草稿。")
            elif notes.status != "published":
                raise conflict("笔记尚未发布。")
        if kind == "chat_reply":
            message = documents["message_id"]
            if (
                message.role != "assistant"
                or message.conversation_id != operation.request.conversation_id
                or message.notes_revision_id != operation.request.notes_revision_id
            ):
                raise conflict("聊天回复的会话或笔记版本不匹配。")

    def retry(self, task_id, operation_id):
        with self._write() as connection:
            operation = self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            if operation.status != "failed" or not operation.error or not operation.error.retryable:
                raise conflict("该操作不可重试。")
            history = OperationAttempt(
                attempt=operation.attempt,
                status="failed",
                usage=operation.usage,
                started_at=operation.started_at,
                finished_at=operation.finished_at,
                error=operation.error,
            )
            operation = operation.model_copy(
                update={
                    "attempt": operation.attempt + 1,
                    "status": "queued",
                    "error": None,
                    "started_at": None,
                    "finished_at": None,
                    "output": OperationOutput(),
                    "cancel_requested": False,
                    "attempts": [*operation.attempts, history],
                    "usage": OperationUsage(
                        request_limit=operation.usage.request_limit,
                        token_limit=operation.usage.token_limit,
                    ),
                }
            )
            self._update_operation(connection, operation)
            return operation

    def request_cancel(self, task_id, operation_id):
        with self._write() as connection:
            operation = self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            if operation.status == "cancelled":
                return operation
            if operation.status not in {"queued", "running"}:
                raise conflict()
            operation.cancel_requested = True
            if operation.status == "queued":
                operation.status, operation.finished_at = "cancelled", now()
            self._update_operation(connection, operation)
            return operation

    def acknowledge_cancel(self, task_id, operation_id):
        # Worker must terminate its owned attempt process before invoking this method.
        with self._write() as connection:
            operation = self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            if operation.status != "running" or not operation.cancel_requested:
                raise conflict()
            operation.status, operation.finished_at = "cancelled", now()
            self._update_operation(connection, operation)
            return operation

    def snapshot(self, task_id, snapshot_id):
        with self.engine.connect() as connection:
            return self._owned(connection, SnapshotRow, TranscriptSnapshot, task_id, snapshot_id)

    def _immutable(self, connection, row, schema, item, values):
        self._course(connection, item.task_id)
        existing = connection.scalar(select(row.payload).where(row.id == str(item.id)))
        if existing:
            old = schema.model_validate(existing)
            if old != item:
                raise conflict("历史记录不可覆盖。")
            return old
        connection.execute(insert(row).values(**values, payload=item.model_dump(mode="json")))
        return item

    def add_snapshot(self, snapshot):
        snapshot = TranscriptSnapshot.model_validate(snapshot)
        with self._write() as connection:
            self._course(connection, snapshot.task_id)
            previous = connection.scalar(
                select(SnapshotRow.payload).where(
                    SnapshotRow.task_id == str(snapshot.task_id),
                    SnapshotRow.sha256 == snapshot.sha256,
                )
            )
            if previous:
                return TranscriptSnapshot.model_validate(previous)
            return self._immutable(
                connection,
                SnapshotRow,
                TranscriptSnapshot,
                snapshot,
                {
                    "id": str(snapshot.id),
                    "task_id": str(snapshot.task_id),
                    "sha256": snapshot.sha256,
                },
            )

    def notes(self, task_id, revision_id):
        with self.engine.connect() as connection:
            return self._owned(connection, NotesRevisionRow, NotesRevision, task_id, revision_id)

    def note_revisions(self, task_id, *, limit=20, offset=0):
        return self._list_versions(task_id, NotesRevisionRow, NotesRevision, limit, offset)

    def quiz_batches(self, task_id, *, limit=20, offset=0):
        return self._list_versions(task_id, QuizBatchRow, QuizBatch, limit, offset)

    def _list_versions(self, task_id, row, schema, limit, offset):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        with self.engine.connect() as connection:
            self._course(connection, task_id)
            values = connection.scalars(
                select(row.payload)
                .where(row.task_id == str(task_id))
                .order_by(row.payload["created_at"].as_string().desc(), row.id.desc())
                .limit(limit)
                .offset(offset)
            )
            return [schema.model_validate(value) for value in values]

    def add_notes(self, revision):
        revision = NotesRevision.model_validate(revision)
        with self._write() as connection:
            self._owned(
                connection,
                SnapshotRow,
                TranscriptSnapshot,
                revision.task_id,
                revision.transcript_snapshot_id,
            )
            for field, row, schema in (
                ("parent_revision_id", NotesRevisionRow, NotesRevision),
                ("operation_id", OperationRow, StudyOperation),
            ):
                if value := getattr(revision, field):
                    self._owned(connection, row, schema, revision.task_id, value)
            return self._immutable(
                connection,
                NotesRevisionRow,
                NotesRevision,
                revision,
                {
                    "id": str(revision.id),
                    "task_id": str(revision.task_id),
                    "transcript_snapshot_id": str(revision.transcript_snapshot_id),
                    "parent_revision_id": str(revision.parent_revision_id)
                    if revision.parent_revision_id
                    else None,
                    "operation_id": str(revision.operation_id) if revision.operation_id else None,
                    "status": revision.status,
                },
            )

    def batch(self, task_id, batch_id):
        with self.engine.connect() as connection:
            return self._owned(connection, QuizBatchRow, QuizBatch, task_id, batch_id)

    def add_batch(self, batch):
        batch = QuizBatch.model_validate(batch)
        with self._write() as connection:
            self._owned(
                connection,
                SnapshotRow,
                TranscriptSnapshot,
                batch.task_id,
                batch.transcript_snapshot_id,
            )
            if batch.notes_revision_id:
                notes = self._owned(
                    connection,
                    NotesRevisionRow,
                    NotesRevision,
                    batch.task_id,
                    batch.notes_revision_id,
                )
                if notes.transcript_snapshot_id != batch.transcript_snapshot_id:
                    raise conflict("自测与笔记的字幕版本不匹配。")
            if batch.operation_id:
                self._owned(
                    connection, OperationRow, StudyOperation, batch.task_id, batch.operation_id
                )
            return self._immutable(
                connection,
                QuizBatchRow,
                QuizBatch,
                batch,
                {
                    "id": str(batch.id),
                    "task_id": str(batch.task_id),
                    "transcript_snapshot_id": str(batch.transcript_snapshot_id),
                    "notes_revision_id": str(batch.notes_revision_id)
                    if batch.notes_revision_id
                    else None,
                    "operation_id": str(batch.operation_id) if batch.operation_id else None,
                    "sequence": batch.sequence,
                    "nonce": str(batch.nonce),
                },
            )

    def _state(self, connection, task_id):
        self._course(connection, task_id)
        payload = connection.scalar(
            select(CourseStateRow.payload).where(CourseStateRow.task_id == str(task_id))
        )
        return (
            CourseStudyState.model_validate(payload)
            if payload
            else CourseStudyState(task_id=task_id)
        )

    def state(self, task_id):
        with self.engine.connect() as connection:
            return self._state(connection, task_id)

    def _save_state(self, connection, state):
        values = state.model_dump(mode="json")
        values.pop("schema_version")
        values["payload"] = state.model_dump(mode="json")
        exists = connection.scalar(
            select(CourseStateRow.task_id).where(CourseStateRow.task_id == str(state.task_id))
        )
        if exists:
            connection.execute(
                update(CourseStateRow)
                .where(CourseStateRow.task_id == str(state.task_id))
                .values(**values)
            )
        else:
            connection.execute(insert(CourseStateRow).values(**values))

    def set_source(self, task_id, snapshot_id, *, expected_revision):
        with self._write() as connection:
            self._owned(connection, SnapshotRow, TranscriptSnapshot, task_id, snapshot_id)
            state = self._state(connection, task_id)
            if state.revision != expected_revision:
                raise conflict()
            if state.transcript_snapshot_id == UUID(str(snapshot_id)):
                return state
            state = state.model_copy(
                update={
                    "revision": state.revision + 1,
                    "transcript_snapshot_id": UUID(str(snapshot_id)),
                    "notes_revision_id": None,
                    "quiz_batch_id": None,
                }
            )
            self._save_state(connection, state)
            return state

    def publish_notes(self, task_id, revision_id, *, expected_current_id):
        with self._write() as connection:
            revision = self._owned(
                connection, NotesRevisionRow, NotesRevision, task_id, revision_id
            )
            state = self._state(connection, task_id)
            expected = UUID(str(expected_current_id)) if expected_current_id else None
            if (
                state.notes_revision_id != expected
                or state.transcript_snapshot_id != revision.transcript_snapshot_id
            ):
                raise conflict("笔记或字幕版本已变化，请重新核对。")
            if revision.status == "draft" and revision.parent_revision_id != expected:
                raise conflict("草稿的基准版本已变化。")
            if revision.status == "draft":
                revision.status = "published"
                connection.execute(
                    update(NotesRevisionRow)
                    .where(NotesRevisionRow.id == str(revision.id))
                    .values(status=revision.status, payload=revision.model_dump(mode="json"))
                )
            state = state.model_copy(
                update={"revision": state.revision + 1, "notes_revision_id": revision.id}
            )
            self._save_state(connection, state)
            return state

    def publish_batch(self, task_id, batch_id, *, expected_current_id):
        with self._write() as connection:
            batch = self._owned(connection, QuizBatchRow, QuizBatch, task_id, batch_id)
            state = self._state(connection, task_id)
            expected = UUID(str(expected_current_id)) if expected_current_id else None
            if (
                state.quiz_batch_id != expected
                or state.transcript_snapshot_id != batch.transcript_snapshot_id
            ):
                raise conflict()
            state = state.model_copy(
                update={"revision": state.revision + 1, "quiz_batch_id": batch.id}
            )
            self._save_state(connection, state)
            return state

    def save_preferences(self, task_id, preferences, *, expected_revision):
        preferences = NotePreferences.model_validate(preferences)
        with self._write() as connection:
            self._course(connection, task_id)
            payload = connection.scalar(
                select(PreferencesRow.payload).where(PreferencesRow.task_id == str(task_id))
            )
            old = CourseNotePreferences.model_validate(payload) if payload else None
            if (old.revision if old else 0) != expected_revision:
                raise conflict("偏好设置已变化。")
            record = CourseNotePreferences(
                task_id=task_id, revision=expected_revision + 1, preferences=preferences
            )
            values = {"revision": record.revision, "payload": record.model_dump(mode="json")}
            if old:
                connection.execute(
                    update(PreferencesRow)
                    .where(PreferencesRow.task_id == str(task_id))
                    .values(**values)
                )
            else:
                connection.execute(insert(PreferencesRow).values(task_id=str(task_id), **values))
            return record

    def preferences(self, task_id):
        with self.engine.connect() as connection:
            self._course(connection, task_id)
            payload = connection.scalar(
                select(PreferencesRow.payload).where(PreferencesRow.task_id == str(task_id))
            )
            return CourseNotePreferences.model_validate(payload) if payload else None

    def conversations(self, task_id):
        with self.engine.connect() as connection:
            self._course(connection, task_id)
            return [
                Conversation.model_validate(p)
                for p in connection.scalars(
                    select(ConversationRow.payload)
                    .where(ConversationRow.task_id == str(task_id))
                    .order_by(ConversationRow.id)
                )
            ]

    def create_conversation(self, task_id):
        record = Conversation(id=uuid4(), task_id=task_id, created_at=now())
        with self._write() as connection:
            self._immutable(
                connection,
                ConversationRow,
                Conversation,
                record,
                {
                    "id": str(record.id),
                    "task_id": str(task_id),
                },
            )
        return record

    def append_message(
        self,
        task_id,
        conversation_id,
        client_message_id,
        *,
        role,
        content,
        notes_revision_id,
        operation_id=None,
        citations=None,
    ):
        with self._write() as connection:
            self._owned(connection, ConversationRow, Conversation, task_id, conversation_id)
            notes = self._owned(
                connection, NotesRevisionRow, NotesRevision, task_id, notes_revision_id
            )
            if notes.status != "published":
                raise conflict("聊天需要已发布笔记。")
            if operation_id:
                self._owned(connection, OperationRow, StudyOperation, task_id, operation_id)
            old = connection.scalar(
                select(MessageRow.payload).where(
                    MessageRow.conversation_id == str(conversation_id),
                    MessageRow.client_message_id == str(client_message_id),
                )
            )
            sequence = (
                connection.scalar(
                    select(MessageRow.sequence)
                    .where(MessageRow.conversation_id == str(conversation_id))
                    .order_by(MessageRow.sequence.desc())
                    .limit(1)
                )
                or 0
            )
            record = ConversationMessage(
                id=uuid4(),
                task_id=task_id,
                conversation_id=conversation_id,
                client_message_id=client_message_id,
                sequence=sequence + 1,
                role=role,
                content=content,
                notes_revision_id=notes_revision_id,
                operation_id=operation_id,
                created_at=now(),
                citations=citations or [],
            )
            if old:
                old = ConversationMessage.model_validate(old)
                fields = ("role", "content", "notes_revision_id", "operation_id", "citations")
                if any(getattr(old, field) != getattr(record, field) for field in fields):
                    raise conflict("消息幂等键冲突。")
                return old
            connection.execute(
                insert(MessageRow).values(
                    id=str(record.id),
                    task_id=str(task_id),
                    conversation_id=str(conversation_id),
                    client_message_id=str(client_message_id),
                    sequence=record.sequence,
                    role=role,
                    notes_revision_id=str(notes_revision_id),
                    operation_id=str(operation_id) if operation_id else None,
                    payload=record.model_dump(mode="json"),
                )
            )
            return record

    def messages(self, task_id, conversation_id, *, after_sequence=0, limit=50):
        if not 1 <= limit <= 100 or after_sequence < 0:
            raise ValueError("Invalid pagination")
        with self.engine.connect() as connection:
            self._owned(connection, ConversationRow, Conversation, task_id, conversation_id)
            rows = connection.scalars(
                select(MessageRow.payload)
                .where(
                    MessageRow.conversation_id == str(conversation_id),
                    MessageRow.sequence > after_sequence,
                )
                .order_by(MessageRow.sequence)
                .limit(limit)
            )
            return [ConversationMessage.model_validate(row) for row in rows]
