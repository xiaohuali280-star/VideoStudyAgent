"""One queue for new study actions; legacy projections are kept for compatibility."""

import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, select, update

from app.core.errors import StudyError
from app.db.models import TaskRow
from app.db.repository import initialize_database, now
from app.db.study_repository import StudyRepository
from app.providers.budget import BoundedLLM
from app.providers.deepseek import DeepSeekClient
from app.schemas.common import ErrorInfo
from app.schemas.iteration import (
    InitialStudyRequest,
    NotesRevision,
    OperationOutput,
    OperationUsage,
    ProcessingOptions,
    QuizBatch,
    QuizGenerationOptions,
    TranscriptSnapshot,
)
from app.schemas.study import NotesDocument, QuizDocumentV11
from app.schemas.tasks import Artifact
from app.services.quiz_documents import QuizReader
from app.services.storage import ArtifactStore, file_hash
from app.services.study_versions import VersionReader
from app.task_runner import execute_study


def ensure_study_schema(settings, engine):
    if "study_operations" in inspect(engine).get_table_names():
        return
    with engine.connect() as connection:
        existing = connection.scalar(select(TaskRow.id).limit(1))
    if existing:
        raise StudyError(
            "MIGRATION_REQUIRED", "现有课程库需要先备份升级，请停止服务后运行迁移命令。", 409
        )
    upgraded = initialize_database(settings.data_dir / "app.db", revision="0003_study_foundation")
    upgraded.dispose()


def enqueue_initial(task, settings, engine):
    return StudyRepository(engine).enqueue(
        task.id,
        InitialStudyRequest(
            processing=ProcessingOptions(
                generate_notes=task.options.generate_notes, generate_quiz=task.options.generate_quiz
            ),
            quiz=QuizGenerationOptions(
                difficulty=task.options.difficulty, output_language=task.options.output_language
            ),
        ),
        f"initial:{task.attempt}",
        usage=OperationUsage(
            request_limit=settings.llm_max_requests, token_limit=settings.llm_total_tokens
        ),
    )


class VersionWriter:
    def __init__(self, root):
        self.store = ArtifactStore(root, None)

    def write(self, task_id, kind, document):
        key = f"tasks/{task_id}/versions/{kind}-{uuid4()}.json"
        path = self.store.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(document.model_dump_json().encode("utf-8"))
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"storage_key": key, "sha256": file_hash(path)}


class ContextRepository:
    def __init__(self, legacy, task_id, artifacts):
        self.legacy, self.task_id = legacy, task_id
        self.current = {item.kind: item for item in artifacts}

    def artifacts(self, task_id):
        if str(task_id) != str(self.task_id):
            raise StudyError("TOOL_FORBIDDEN", "课程上下文不匹配。", 403)
        return list(self.current.values())

    def save_artifact(self, artifact):
        self.legacy.save_artifact(artifact)
        self.current[artifact.kind] = artifact

    def __getattr__(self, name):
        return getattr(self.legacy, name)


def as_artifact(record, kind):
    return Artifact(
        id=record.id,
        task_id=record.task_id,
        kind=kind,
        storage_key=record.storage_key,
        sha256=record.sha256,
        created_at=record.created_at,
    )


async def run_operation(operation, settings, repository, llm=None, asr=None):
    repo = StudyRepository(repository.engine)
    task = repository.get(operation.task_id)
    request = operation.request
    try:
        bounded = None
        if (
            request.kind != "initial_study"
            or request.processing.generate_notes
            or request.processing.generate_quiz
        ):
            limits = settings.model_copy(
                update={
                    "llm_max_requests": min(
                        settings.llm_max_requests, operation.usage.request_limit
                    ),
                    "llm_total_tokens": min(settings.llm_total_tokens, operation.usage.token_limit),
                }
            )
            bounded = BoundedLLM(llm or DeepSeekClient(limits), limits)
            bounded.requests_reserved = operation.usage.requests_reserved
            bounded.tokens_reserved = operation.usage.tokens_reserved
            bounded.actual_input_tokens = operation.usage.input_tokens or 0
            bounded.actual_output_tokens = operation.usage.output_tokens or 0
            bounded.usage_known = operation.usage.input_tokens is not None

            def record(client):
                repo.record_usage(
                    task.id,
                    operation.id,
                    OperationUsage(
                        request_limit=operation.usage.request_limit,
                        token_limit=operation.usage.token_limit,
                        requests_reserved=client.requests_reserved,
                        tokens_reserved=client.tokens_reserved,
                        input_tokens=client.actual_input_tokens if client.usage_known else None,
                        output_tokens=client.actual_output_tokens if client.usage_known else None,
                    ),
                )

            bounded.on_usage = record
        if request.kind == "chat_reply":
            from app.services.note_chat import reply_to_notes

            await reply_to_notes(operation, bounded.settings, repository, bounded)
            return
        if operation.legacy_options is not None:
            raise StudyError(
                "LEGACY_ACTION_REQUIRED", "旧待处理任务请重新确认生成选项后提交。", 409, True
            )
        if request.kind == "initial_study":
            with repository.engine.begin() as connection:
                value = task.model_copy(update={"status": "running", "started_at": now()})
                connection.execute(
                    update(TaskRow)
                    .where(TaskRow.id == str(task.id))
                    .values(status="running", payload=value.model_dump(mode="json"))
                )
            task = value
            context = repository
        elif request.kind in {"generate_notes", "generate_quiz"}:
            source = repo.snapshot(task.id, request.transcript_snapshot_id)
            VersionReader(settings.data_dir).transcript(source)
            artifacts = [as_artifact(source, "transcript")]
            if request.kind == "generate_quiz" and request.notes_revision_id:
                notes = repo.notes(task.id, request.notes_revision_id)
                VersionReader(settings.data_dir).notes(notes)
                artifacts.append(as_artifact(notes, "notes"))
            context = ContextRepository(repository, task.id, artifacts)
            options = task.options.model_copy(
                update={
                    "question_count": 5,
                    "generate_notes": request.kind == "generate_notes",
                    "generate_quiz": request.kind == "generate_quiz",
                    "difficulty": request.options.difficulty
                    if request.kind == "generate_quiz"
                    else task.options.difficulty,
                    "output_language": request.options.output_language
                    if request.kind == "generate_quiz"
                    else request.output_language,
                }
            )
            task = task.model_copy(update={"options": options})
        else:
            raise StudyError("OPERATION_UNAVAILABLE", "此操作尚未接入。", 409)
        if request.kind == "initial_study":
            context = ContextRepository(repository, task.id, repository.artifacts(task.id))
        context.quiz_nonce = str(operation.id)
        reader = VersionReader(settings.data_dir)
        context.previous_questions = [
            q.question
            for batch in repo.quiz_batches(task.id, limit=100)
            for q in reader.quiz(batch).questions
        ]
        tools = await execute_study(
            task, bounded.settings if bounded else settings, context, bounded, asr
        )
        artifacts = {item.kind: item for item in context.artifacts(task.id)}
        source_artifact = artifacts["transcript"]
        source = repo.add_snapshot(
            TranscriptSnapshot(
                id=uuid4(),
                task_id=task.id,
                storage_key=source_artifact.storage_key,
                sha256=source_artifact.sha256,
                created_at=source_artifact.created_at,
            )
        )
        state = repo.state(task.id)
        if state.transcript_snapshot_id is None:
            state = repo.set_source(task.id, source.id, expected_revision=state.revision)
        writer = VersionWriter(settings.data_dir)
        note_id = getattr(request, "notes_revision_id", None)
        batch_id = None
        if task.options.generate_notes:
            document = tools.store.read_json(artifacts["notes"], NotesDocument)
            revision = repo.add_notes(
                NotesRevision(
                    id=uuid4(),
                    task_id=task.id,
                    transcript_snapshot_id=source.id,
                    parent_revision_id=state.notes_revision_id,
                    operation_id=operation.id,
                    created_at=now(),
                    document_schema_version="1.0",
                    **writer.write(task.id, "notes", document),
                )
            )
            state = repo.publish_notes(
                task.id, revision.id, expected_current_id=state.notes_revision_id
            )
            note_id = revision.id
        if task.options.generate_quiz:
            document = tools.store.read_json(artifacts["quiz"], QuizReader)
            document = QuizDocumentV11.model_validate(
                document.model_dump() | {"schema_version": "1.1"}
            )
            old_batches = repo.quiz_batches(task.id, limit=100)
            batch = repo.add_batch(
                QuizBatch(
                    id=uuid4(),
                    task_id=task.id,
                    transcript_snapshot_id=source.id,
                    notes_revision_id=note_id,
                    operation_id=operation.id,
                    sequence=max([b.sequence for b in old_batches] or [0]) + 1,
                    nonce=operation.id,
                    difficulty=task.options.difficulty,
                    created_at=now(),
                    **writer.write(task.id, "quiz", document),
                )
            )
            repo.publish_batch(task.id, batch.id, expected_current_id=state.quiz_batch_id)
            batch_id = batch.id
        output = OperationOutput(
            transcript_snapshot_id=source.id,
            notes_revision_id=note_id if task.options.generate_notes else None,
            quiz_batch_id=batch_id,
        )
        repo.finish(task.id, operation.id, output=output)
        if request.kind == "initial_study":
            repository.finish(task.id)
    except StudyError as error:
        safe = ErrorInfo(
            code=error.code,
            message=error.message,
            retryable=error.retryable or error.code == "LLM_CONFIGURATION_ERROR",
        )
        repo.finish(task.id, operation.id, error=safe)
        if request.kind == "initial_study" and repository.get(task.id).status == "running":
            repository.finish(task.id, safe)
    except Exception:
        safe = ErrorInfo(code="INTERNAL_ERROR", message="操作执行未完成。", retryable=True)
        repo.finish(task.id, operation.id, error=safe)
        if request.kind == "initial_study" and repository.get(task.id).status == "running":
            repository.finish(task.id, safe)
