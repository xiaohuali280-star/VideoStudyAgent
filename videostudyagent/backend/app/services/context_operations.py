"""Multimodal adaptation of the existing operation/Agent/version machinery."""

from uuid import uuid4

from sqlalchemy import inspect, select, update

from app.core.errors import StudyError
from app.db.context_repository import VideoContextRepository
from app.db.models import TaskRow
from app.db.repository import initialize_database, now
from app.db.study_repository import StudyRepository
from app.schemas.iteration import NotesRevision, OperationOutput, QuizBatch
from app.schemas.video_context import VideoContextSnapshot
from app.services.note_documents import NoteReader
from app.services.quiz_documents import QuizReader
from app.services.source_context import validate_context_document
from app.services.storage import ArtifactStore, cache_key
from app.services.study_versions import VersionReader


def ensure_context_schema(settings, engine):
    if "video_context_snapshots" in inspect(engine).get_table_names():
        return
    with engine.connect() as connection:
        if connection.scalar(select(TaskRow.id).limit(1)):
            raise StudyError("MIGRATION_REQUIRED", "请停机备份后显式升级 V3 数据库。", 409)
    upgraded = initialize_database(settings.data_dir / "app.db", revision="0007_operation_events")
    upgraded.dispose()


async def run_context_operation(operation, settings, repository, bounded, asr=None):
    from app.services.operations import ContextRepository, VersionWriter
    from app.task_runner import execute_study

    repo = StudyRepository(repository.engine)
    task, request = repository.get(operation.task_id), operation.request
    state = repo.state(task.id)
    if request.kind == "revise_notes":
        from app.services.context_revision import revise_context_notes

        await revise_context_notes(operation, settings, repository, bounded)
        return
    if request.kind == "initial_study":
        task = task.model_copy(update={"status": "running", "started_at": now()})
        with repository.engine.begin() as connection:
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == str(task.id))
                .values(status="running", payload=task.model_dump(mode="json"))
            )
        artifacts = repository.artifacts(task.id)
    else:
        snapshot = VideoContextRepository(repository.engine).get(
            task.id, request.context_snapshot_id
        )
        artifact = ArtifactStore(settings.data_dir, repository).put_json(
            task.id, "context", snapshot, cache_key(context=snapshot.manifest_sha256)
        )
        artifacts = [artifact]
        if request.kind == "generate_quiz" and request.notes_revision_id:
            from app.services.operations import as_artifact

            record = repo.notes(task.id, request.notes_revision_id)
            VersionReader(settings.data_dir).notes(record)
            artifacts.append(as_artifact(record, "notes"))
        task = task.model_copy(
            update={
                "options": task.options.model_copy(
                    update={
                        "enable_ocr": True,
                        "question_count": 5,
                        "generate_notes": request.kind == "generate_notes",
                        "generate_quiz": request.kind == "generate_quiz",
                        "difficulty": request.options.difficulty
                        if request.kind == "generate_quiz"
                        else task.options.difficulty,
                    }
                )
            }
        )
    context = ContextRepository(repository, task.id, artifacts)
    context.context_mode = True
    context.ocr_provider = getattr(repository, "ocr_provider", None)
    context.frame_extractor = getattr(repository, "frame_extractor", None)
    context.note_preferences = (
        getattr(request, "preferences", None).model_dump(mode="json")
        if getattr(request, "preferences", None)
        else {}
    )
    context.operation_id = operation.id
    context.quiz_nonce = str(operation.id)
    reader = VersionReader(settings.data_dir)
    context.previous_questions = [
        q.question for b in repo.quiz_batches(task.id, limit=100) for q in reader.quiz(b).questions
    ]
    tools = await execute_study(task, settings, context, bounded, asr)
    stored = {a.kind: a for a in context.artifacts(task.id)}
    snapshot = tools.store.read_json(stored["context"], VideoContextSnapshot)
    from app.services.indexing import index_source

    indexed = index_source(repository, settings.data_dir, task.id, snapshot.id, "context")
    repo.progress(
        task.id,
        operation.id,
        "indexing",
        completed_units=1 if indexed else None,
        total_units=1 if indexed else None,
    )
    if state.context_snapshot_id != snapshot.id:
        state = repo.set_context_source(task.id, snapshot.id, expected_revision=state.revision)
    writer = VersionWriter(settings.data_dir)
    note_id, batch_id = getattr(request, "notes_revision_id", None), None
    if task.options.generate_notes:
        document = tools.store.read_json(stored["notes"], NoteReader)
        validate_context_document(document, snapshot, require_coverage=True)
        from app.services.generation import GenerationService
        from app.services.review_runtime import review_candidate

        document, approval = await review_candidate(
            operation,
            document,
            snapshot,
            snapshot.id,
            GenerationService(settings, context, bounded),
            lambda d: validate_context_document(d, snapshot, require_coverage=True),
        )
        revision = repo.add_notes(
            NotesRevision(
                id=uuid4(),
                task_id=task.id,
                transcript_snapshot_id=snapshot.transcript_snapshot_id,
                context_snapshot_id=snapshot.id,
                parent_revision_id=state.notes_revision_id,
                operation_id=operation.id,
                document_schema_version="1.2",
                **approval,
                preferences=request.preferences,
                created_at=now(),
                **writer.write(task.id, "notes", document),
            )
        )
        state = repo.publish_notes(
            task.id, revision.id, expected_current_id=state.notes_revision_id
        )
        note_id = revision.id
    if task.options.generate_quiz:
        document = tools.store.read_json(stored["quiz"], QuizReader)
        basis = reader.notes(repo.notes(task.id, note_id)) if note_id else None
        validate_context_document(document, snapshot, notes=basis)
        from app.services.generation import GenerationService
        from app.services.review_runtime import review_candidate

        document, approval = await review_candidate(
            operation,
            document,
            snapshot,
            snapshot.id,
            GenerationService(settings, context, bounded),
            lambda d: validate_context_document(d, snapshot, notes=basis),
        )
        batches = repo.quiz_batches(task.id, limit=100)
        batch = repo.add_batch(
            QuizBatch(
                id=uuid4(),
                task_id=task.id,
                transcript_snapshot_id=snapshot.transcript_snapshot_id,
                context_snapshot_id=snapshot.id,
                notes_revision_id=note_id,
                operation_id=operation.id,
                document_schema_version="1.2",
                **approval,
                sequence=max([b.sequence for b in batches] or [0]) + 1,
                nonce=operation.id,
                difficulty=task.options.difficulty,
                created_at=now(),
                **writer.write(task.id, "quiz", document),
            )
        )
        repo.publish_batch(task.id, batch.id, expected_current_id=state.quiz_batch_id)
        batch_id = batch.id
    repo.finish(
        task.id,
        operation.id,
        output=OperationOutput(
            context_snapshot_id=snapshot.id,
            transcript_snapshot_id=snapshot.transcript_snapshot_id,
            notes_revision_id=note_id if task.options.generate_notes else None,
            quiz_batch_id=batch_id,
        ),
    )
    if request.kind == "initial_study":
        repository.finish(task.id)
