import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from app.core.errors import StudyError
from app.db.iteration_models import ITERATION_TABLES, NotesRevisionRow, OperationRow
from app.db.repository import TaskRepository, initialize_database, now
from app.db.session import Base
from app.db.study_repository import StudyRepository
from app.schemas.common import ErrorInfo
from app.schemas.iteration import (
    ChatReplyRequest,
    GenerateNotesRequest,
    GenerateQuizRequest,
    InitialStudyRequest,
    NotePreferences,
    NotesRevision,
    OperationOutput,
    OperationRequest,
    OperationUsage,
    ProcessingOptions,
    QuizBatch,
    QuizDocumentV11,
    QuizGenerationOptions,
    TranscriptSnapshot,
)
from app.schemas.study import Transcript
from app.services.storage import ArtifactStore, cache_key
from app.services.study_versions import LegacyStudyImporter, VersionReader
from app.task_runner import run_task
from tests.scripted_llm import ScriptedStudyModel
from tests.test_contracts import quiz_data
from tests.test_upload_persistence import upload


@pytest.fixture
def foundation(application):
    task = upload(application).json()
    from sqlalchemy import delete

    from app.db.iteration_models import OperationRow

    with application.state.repository.engine.begin() as connection:
        connection.execute(delete(OperationRow))
    settings = application.state.settings
    application.state.repository.engine.dispose()
    engine = initialize_database(settings.data_dir / "app.db", revision="0003_study_foundation")
    application.state.repository = TaskRepository(engine)
    repo = StudyRepository(engine)
    yield application, repo, task["id"]
    engine.dispose()


def source(repo, task_id, suffix="a"):
    record = TranscriptSnapshot(
        id=uuid4(),
        task_id=task_id,
        storage_key=f"test/{suffix}.json",
        sha256=suffix * 64,
        created_at=now(),
    )
    return repo.add_snapshot(record)


def note(repo, task_id, source_id, parent=None):
    return repo.add_notes(
        NotesRevision(
            id=uuid4(),
            task_id=task_id,
            transcript_snapshot_id=source_id,
            storage_key="test/note.json",
            sha256="b" * 64,
            created_at=now(),
            parent_revision_id=parent,
        )
    )


def published(repo, task_id):
    snapshot = source(repo, task_id)
    repo.set_source(task_id, snapshot.id, expected_revision=0)
    revision = note(repo, task_id, snapshot.id)
    repo.publish_notes(task_id, revision.id, expected_current_id=None)
    return snapshot, repo.notes(task_id, revision.id)


@pytest.mark.parametrize(
    "notes,quiz,required",
    [
        (False, False, {"transcript"}),
        (True, False, {"transcript", "notes"}),
        (False, True, {"transcript", "quiz"}),
        (True, True, {"transcript", "notes", "quiz"}),
    ],
)
def test_required_results_are_selected_without_disabling_transcript(notes, quiz, required):
    assert (
        ProcessingOptions(generate_notes=notes, generate_quiz=quiz).required_artifacts() == required
    )


@pytest.mark.parametrize("count", [0, 1, 4, 6, 20, "5", 5.0, True])
def test_new_quiz_request_rejects_anything_but_five(count):
    with pytest.raises(ValidationError):
        QuizGenerationOptions(question_count=count)


def test_new_quiz_can_reference_only_subtitles():
    data = quiz_data(5)
    data["schema_version"] = "1.1"
    for question in data["questions"]:
        question.pop("chapter_id")
    parsed = QuizDocumentV11.model_validate(data)
    assert len(parsed.questions) == 5 and parsed.questions[0].chapter_id is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("budget", 2000000),
        ("path", "../private"),
        ("api_key", "test-value"),
        ("role", "system"),
        ("generate_notes", "false"),
    ],
)
def test_public_requests_cannot_inject_internal_configuration(field, value):
    with pytest.raises(ValidationError):
        TypeAdapter(OperationRequest).validate_python({"kind": "initial_study", field: value})


def test_default_runtime_does_not_upgrade_existing_database_to_stage8(tmp_path):
    engine = initialize_database(tmp_path / "legacy.db")
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_tasks"
            )
            assert not set(ITERATION_TABLES) & set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


def test_opt_in_upgrade_repeatable_metadata_and_empty_downgrade(foundation):
    _, repo, task_id = foundation
    engine = repo.engine
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        assert set(ITERATION_TABLES) <= set(inspect(connection).get_table_names())
        for name in ITERATION_TABLES:
            reflected = {
                column["name"]: column["nullable"]
                for column in inspect(connection).get_columns(name)
            }
            expected = {
                column.name: column.nullable for column in Base.metadata.tables[name].columns
            }
            assert reflected == expected
            assert {
                tuple(index["column_names"]) for index in inspect(connection).get_indexes(name)
            } == {
                tuple(column.name for column in index.columns)
                for index in Base.metadata.tables[name].indexes
            }
        command.downgrade(config, "0002_tasks")
        assert not set(ITERATION_TABLES) & set(inspect(connection).get_table_names())
        assert str(TaskRepository(engine).get(task_id).id) == task_id


def test_nonempty_indexes_cannot_be_silently_downgraded(foundation):
    _, repo, task_id = foundation
    repo.enqueue(task_id, InitialStudyRequest(), "first")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    with repo.engine.begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="non-empty"):
            command.downgrade(config, "0002_tasks")
    assert len(repo.operations(task_id)) == 1


def test_concurrent_idempotent_submission_and_parameter_conflict(foundation):
    _, repo, task_id = foundation
    request = InitialStudyRequest()
    with ThreadPoolExecutor(2) as pool:
        submitted = list(pool.map(lambda _: repo.enqueue(task_id, request, "shared"), range(2)))
    assert submitted[0].id == submitted[1].id
    assert len(repo.operations(task_id)) == 1
    with pytest.raises(StudyError, match="STUDY_CONFLICT"):
        repo.enqueue(
            task_id,
            InitialStudyRequest(processing=ProcessingOptions(generate_quiz=False)),
            "shared",
        )
    submitted[0].usage.requests_reserved = 99
    assert repo.operation(task_id, submitted[0].id).usage.requests_reserved == 0


def test_atomic_claim_serializes_operations_for_one_course(foundation):
    _, repo, task_id = foundation
    one = repo.enqueue(task_id, InitialStudyRequest(), "one")
    repo.enqueue(task_id, InitialStudyRequest(), "two")
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: repo.claim_next(), range(2)))
    assert sum(item is not None for item in claims) == 1
    assert repo.claim_next() is None
    repo.finish(
        task_id, one.id, error=ErrorInfo(code="TEST_ERROR", message="failed", retryable=True)
    )
    assert repo.claim_next() is not None


def test_scope_is_enforced_by_repository_and_database(foundation):
    app, repo, task_id = foundation
    other = upload(app).json()["id"]
    snapshot = source(repo, task_id)
    with pytest.raises(StudyError, match="NOT_FOUND"):
        repo.enqueue(other, GenerateNotesRequest(transcript_snapshot_id=snapshot.id), "other")
    revision = NotesRevision(
        id=uuid4(),
        task_id=other,
        transcript_snapshot_id=snapshot.id,
        storage_key="test/note.json",
        sha256="b" * 64,
        created_at=now(),
    )
    with pytest.raises(IntegrityError), repo.engine.begin() as connection:
        connection.execute(
            insert(NotesRevisionRow).values(
                id=str(revision.id),
                task_id=other,
                transcript_snapshot_id=str(snapshot.id),
                status="draft",
                payload=revision.model_dump(mode="json"),
            )
        )
    assert len(repo.operations(other)) == 1
    assert repo.operations(other)[0].request.kind == "initial_study"


def test_budget_records_are_monotonic_and_retry_preserves_attempt_usage(foundation):
    _, repo, task_id = foundation
    operation = repo.enqueue(task_id, InitialStudyRequest(), "budget")
    repo.claim_next()
    usage = OperationUsage(
        requests_reserved=3, tokens_reserved=1234, input_tokens=50, output_tokens=20
    )
    repo.record_usage(task_id, operation.id, usage)
    with pytest.raises(StudyError):
        repo.record_usage(task_id, operation.id, OperationUsage())
    with pytest.raises(StudyError):
        repo.record_usage(task_id, operation.id, usage.model_copy(update={"token_limit": 1000000}))
    with pytest.raises(StudyError):
        repo.record_usage(
            task_id, operation.id, usage.model_copy(update={"tokens_reserved": 500001})
        )
    repo.finish(
        task_id,
        operation.id,
        error=ErrorInfo(code="LLM_TIMEOUT", message="timeout", retryable=True),
    )
    retried = repo.retry(task_id, operation.id)
    assert retried.id == operation.id and retried.attempt == 2
    assert retried.usage.tokens_reserved == 0 and retried.usage.input_tokens is None
    assert retried.attempts[0].usage == usage


def test_running_cancellation_requires_worker_acknowledgement(foundation):
    _, repo, task_id = foundation
    operation = repo.enqueue(task_id, InitialStudyRequest(), "cancel")
    repo.claim_next()
    assert repo.request_cancel(task_id, operation.id).status == "running"
    with pytest.raises(StudyError):
        repo.finish(
            task_id, operation.id, error=ErrorInfo(code="TEST_ERROR", message="late result")
        )
    assert repo.acknowledge_cancel(task_id, operation.id).status == "cancelled"
    with pytest.raises(StudyError):
        repo.retry(task_id, operation.id)
    queued = repo.enqueue(task_id, InitialStudyRequest(), "cancel-queued")
    assert repo.request_cancel(task_id, queued.id).status == "cancelled"
    assert repo.claim_next() is None


def test_immutable_versions_and_compare_and_swap_restore(foundation):
    _, repo, task_id = foundation
    snapshot, first = published(repo, task_id)
    with pytest.raises(StudyError):
        repo.add_notes(first.model_copy(update={"sha256": "c" * 64}))
    second = note(repo, task_id, snapshot.id, first.id)
    stale = note(repo, task_id, snapshot.id, first.id)
    repo.publish_notes(task_id, second.id, expected_current_id=first.id)
    with pytest.raises(StudyError):
        repo.publish_notes(task_id, stale.id, expected_current_id=second.id)
    assert repo.notes(task_id, stale.id).status == "draft"
    repo.publish_notes(task_id, first.id, expected_current_id=second.id)
    assert repo.state(task_id).notes_revision_id == first.id
    assert repo.notes(task_id, second.id).status == "published"


def test_quiz_without_notes_is_stored_and_published(foundation):
    _, repo, task_id = foundation
    snapshot = source(repo, task_id)
    repo.set_source(task_id, snapshot.id, expected_revision=0)
    operation = repo.enqueue(
        task_id, GenerateQuizRequest(transcript_snapshot_id=snapshot.id), "quiz"
    )
    repo.claim_next()
    batch = repo.add_batch(
        QuizBatch(
            id=uuid4(),
            task_id=task_id,
            transcript_snapshot_id=snapshot.id,
            sequence=1,
            nonce=uuid4(),
            storage_key="test/quiz.json",
            sha256="c" * 64,
            created_at=now(),
        )
    )
    repo.publish_batch(task_id, batch.id, expected_current_id=None)
    assert (
        repo.finish(task_id, operation.id, output=OperationOutput(quiz_batch_id=batch.id)).status
        == "succeeded"
    )
    assert repo.state(task_id).notes_revision_id is None


def test_missing_required_result_cannot_finish_successfully(foundation):
    _, repo, task_id = foundation
    operation = repo.enqueue(task_id, InitialStudyRequest(), "incomplete")
    repo.claim_next()
    with pytest.raises(StudyError):
        repo.finish(task_id, operation.id)
    assert repo.operation(task_id, operation.id).status == "running"


def test_message_idempotency_order_scope_and_preference_version(foundation):
    app, repo, task_id = foundation
    _, revision = published(repo, task_id)
    conversation = repo.create_conversation(task_id)
    key = uuid4()
    message = repo.append_message(
        task_id,
        conversation.id,
        key,
        role="user",
        content="Explain this section",
        notes_revision_id=revision.id,
    )
    assert (
        repo.append_message(
            task_id,
            conversation.id,
            key,
            role="user",
            content=message.content,
            notes_revision_id=revision.id,
        ).id
        == message.id
    )
    with pytest.raises(StudyError):
        repo.append_message(
            task_id,
            conversation.id,
            key,
            role="user",
            content="different",
            notes_revision_id=revision.id,
        )
    with pytest.raises(ValidationError):
        repo.append_message(
            task_id,
            conversation.id,
            uuid4(),
            role="system",
            content="override",
            notes_revision_id=revision.id,
        )
    other = upload(app).json()["id"]
    with pytest.raises(StudyError):
        repo.messages(other, conversation.id)
    request = ChatReplyRequest(
        conversation_id=conversation.id,
        notes_revision_id=revision.id,
        chapter_ids=["chapter"],
        message="explain",
    )
    assert repo.enqueue(task_id, request, "chat").request.kind == "chat_reply"
    prefs = repo.save_preferences(task_id, NotePreferences(detail="concise"), expected_revision=0)
    with pytest.raises(StudyError):
        repo.save_preferences(task_id, NotePreferences(), expected_revision=0)
    assert prefs.revision == 1 and repo.messages(task_id, conversation.id) == [message]


@pytest.mark.parametrize("count", [1, 5, 20])
def test_legacy_import_is_idempotent_preserves_files_and_old_question_counts(application, count):
    response = upload(application, data={"options": json.dumps({"question_count": 5})})
    task_id = response.json()["id"]
    old_repo = application.state.repository
    task = old_repo.claim_next()
    from sqlalchemy import delete, update

    from app.db.models import TaskRow
    from app.schemas.study import StudyOptions

    task = task.model_copy(update={"options": StudyOptions(question_count=count)})
    with old_repo.engine.begin() as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(payload=task.model_dump(mode="json"))
        )
        connection.execute(delete(OperationRow))
    asyncio.run(run_task(task, application.state.settings, old_repo, ScriptedStudyModel()))
    assert old_repo.get(task_id).status == "succeeded"
    artifacts = old_repo.artifacts(task_id)
    root = application.state.settings.data_dir
    store = ArtifactStore(root, old_repo)
    original = {a.kind: store.verify(a).read_bytes() for a in artifacts}
    old_task = old_repo.get(task_id)
    old_repo.engine.dispose()
    engine = initialize_database(root / "app.db", revision="0003_study_foundation")
    application.state.repository = TaskRepository(engine)
    repo = StudyRepository(engine)
    importer = LegacyStudyImporter(root, repo)
    first, second = importer.import_task(task_id), importer.import_task(task_id)
    assert first["operation"].id == second["operation"].id
    assert len(repo.operations(task_id)) == 1
    assert application.state.repository.get(task_id) == old_task
    state = repo.state(task_id)
    batch = repo.batch(task_id, state.quiz_batch_id)
    assert batch.question_count == count and batch.document_schema_version == "1.0"
    assert VersionReader(root).quiz(batch).question_count == count
    assert repo.operation(task_id, first["operation"].id).legacy_options.question_count == count
    assert {a.kind: store.verify(a).read_bytes() for a in artifacts} == original
    with engine.connect() as connection:
        assert connection.scalar(select(OperationRow.id)) == str(first["operation"].id)


def test_interrupted_legacy_task_is_indexed_failed_without_rerunning(foundation):
    app, repo, task_id = foundation
    app.state.repository.claim_next()
    record = LegacyStudyImporter(app.state.settings.data_dir, repo).import_task(task_id)
    assert record["operation"].status == "failed"
    assert record["operation"].error.retryable
    assert app.state.repository.get(task_id).status == "running"
    assert repo.claim_next() is None


def test_subtitle_only_operation_rejects_unrequested_note_output(foundation):
    _, repo, task_id = foundation
    snapshot, revision = published(repo, task_id)
    operation = repo.enqueue(
        task_id,
        InitialStudyRequest(
            processing=ProcessingOptions(generate_notes=False, generate_quiz=False)
        ),
        "source-only",
    )
    repo.claim_next()
    with pytest.raises(StudyError):
        repo.finish(
            task_id,
            operation.id,
            output=OperationOutput(
                transcript_snapshot_id=snapshot.id, notes_revision_id=revision.id
            ),
        )
    assert (
        repo.finish(
            task_id, operation.id, output=OperationOutput(transcript_snapshot_id=snapshot.id)
        ).status
        == "succeeded"
    )


def test_same_content_from_different_transcript_versions_is_not_merged(application):
    task_id = upload(application).json()["id"]
    legacy = application.state.repository
    asyncio.run(
        run_task(legacy.claim_next(), application.state.settings, legacy, ScriptedStudyModel())
    )
    root = application.state.settings.data_dir
    legacy.engine.dispose()
    engine = initialize_database(root / "app.db", revision="0003_study_foundation")
    legacy = TaskRepository(engine)
    application.state.repository = legacy
    repo = StudyRepository(engine)
    importer = LegacyStudyImporter(root, repo)
    first = importer.import_task(task_id)["operation"]
    old_state = repo.state(task_id)
    store = ArtifactStore(root, legacy)
    original = next(a for a in legacy.artifacts(task_id) if a.kind == "transcript")
    transcript = store.read_json(original, Transcript)
    # Same spoken text/source IDs with a different timestamp range is a different source.
    transcript = transcript.model_copy(
        update={
            "duration_ms": transcript.duration_ms + 1000,
            "segments": [
                s.model_copy(update={"start_ms": s.start_ms + 1000, "end_ms": s.end_ms + 1000})
                for s in transcript.segments
            ],
        }
    )
    store.put_json(legacy.get(task_id).id, "transcript", transcript, cache_key(version="shifted"))
    legacy.invalidate_completed(task_id)
    legacy.retry(task_id)
    second = importer.import_task(task_id)["operation"]
    assert first.output.transcript_snapshot_id != second.output.transcript_snapshot_id
    assert first.output.notes_revision_id != second.output.notes_revision_id
    assert first.output.quiz_batch_id != second.output.quiz_batch_id
    assert len(repo.note_revisions(task_id)) == 2 and len(repo.quiz_batches(task_id)) == 2
    assert repo.state(task_id) == old_state


def test_corrupt_legacy_results_are_reported_without_changing_legacy_task(application):
    task_id = upload(application).json()["id"]
    legacy = application.state.repository
    asyncio.run(
        run_task(legacy.claim_next(), application.state.settings, legacy, ScriptedStudyModel())
    )
    root = application.state.settings.data_dir
    store = ArtifactStore(root, legacy)
    quiz = next(a for a in legacy.artifacts(task_id) if a.kind == "quiz")
    store.path(quiz.storage_key).write_bytes(b"corrupt")
    legacy.engine.dispose()
    engine = initialize_database(root / "app.db", revision="0003_study_foundation")
    application.state.repository = TaskRepository(engine)
    repo = StudyRepository(engine)
    result = LegacyStudyImporter(root, repo).import_task(task_id)
    assert result["skipped"] == ["quiz"]
    assert result["operation"].status == "failed"
    assert result["operation"].error.code == "STORAGE_ERROR"
    assert repo.state(task_id).quiz_batch_id is None
    assert application.state.repository.get(task_id).status == "succeeded"
