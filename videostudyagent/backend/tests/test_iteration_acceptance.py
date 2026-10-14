import asyncio
import json
import sqlite3

import pytest
from filelock import Timeout
from sqlalchemy import update

from app.core.locking import native_lock
from app.db.iteration_models import OperationRow
from app.db.models import TaskRow
from app.db.repository import initialize_database
from app.db.study_repository import StudyRepository
from app.main import create_app
from app.migrate_study import migrate
from app.operation_worker import OperationWorker
from app.schemas.common import ErrorInfo
from app.schemas.iteration import (
    ChatReplyRequest,
    GenerateQuizRequest,
    NotePreferences,
    ReviseNotesRequest,
)
from app.services.operations import run_operation
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def test_migration_backup_lock_idempotence_and_old_read_only(application):
    # Build a v1 database directly, without the new upload API.
    settings = application.state.settings
    engine = initialize_database(settings.data_dir / "app.db")
    engine.dispose()
    original = (settings.data_dir / "app.db").read_bytes()
    with native_lock(settings.data_dir / ".worker.lock"):
        with pytest.raises(Timeout):
            migrate(settings)
    assert (settings.data_dir / "app.db").read_bytes() == original
    assert migrate(settings) == 0
    backup = next((settings.data_dir / "backups").glob("*.db"))
    with sqlite3.connect(backup) as connection:
        assert (
            connection.execute("select version_num from alembic_version").fetchone()[0]
            == "0002_tasks"
        )
    assert migrate(settings) == 0
    assert len(list((settings.data_dir / "backups").glob("*.db"))) == 2


def test_queued_cancel_and_restart_require_explicit_retry(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    op = study.operations(task_id)[0]
    cancelled = request(application, "POST", f"/api/tasks/{task_id}/operations/{op.id}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert repo.get(task_id).status == "failed"
    assert study.claim_next() is None
    assert request(application, "POST", f"/api/tasks/{task_id}/retry").status_code == 202
    claimed = study.claim_next()
    worker = OperationWorker(application.state.settings, repo)
    with native_lock(application.state.settings.data_dir / "tasks" / task_id / ".attempt.lock"):
        worker.recover()
        assert study.operation(task_id, claimed.id).status == "running"
    worker.recover()
    assert study.operation(task_id, claimed.id).status == "failed"
    assert repo.get(task_id).status == "failed"
    assert study.claim_next() is None


@pytest.mark.parametrize("bad_count", [0, 4, 6])
def test_new_upload_counts_rejected_before_saving(application, bad_count):
    response = upload(application, data={"options": json.dumps({"question_count": bad_count})})
    assert response.status_code == 422
    assert request(application, "GET", "/api/tasks").json() == []


def test_worker_exception_is_sanitized_and_does_not_leave_queued_task(application):
    task_id = upload(application).json()["id"]

    def broken(operation):
        raise RuntimeError("private-token-must-not-leak")

    repo = application.state.repository
    assert OperationWorker(application.state.settings, repo, broken).run_once()
    assert repo.get(task_id).status == "failed"
    response = request(application, "GET", f"/api/tasks/{task_id}/operations")
    assert "private-token-must-not-leak" not in response.text


def test_versions_messages_batches_survive_new_api_instance(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    model = ScriptedStudyModel()

    def execute(client=model):
        op = study.claim_next()
        asyncio.run(run_operation(op, application.state.settings, repo, client))
        result = study.operation(task_id, op.id)
        assert result.status == "succeeded", result.error
        return result

    execute()
    task = repo.get(task_id).model_copy(update={"status": "running"})
    with repo.engine.begin() as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(status="running", payload=task.model_dump(mode="json"))
        )
    OperationWorker(application.state.settings, repo).recover()
    assert repo.get(task_id).status == "succeeded"
    state = study.state(task_id)
    conversation = study.create_conversation(task_id)
    notes = request(application, "GET", f"/api/tasks/{task_id}/result").json()["notes"]
    study.enqueue(
        task_id,
        ChatReplyRequest(
            conversation_id=conversation.id,
            notes_revision_id=state.notes_revision_id,
            chapter_ids=[notes["chapters"][0]["id"]],
            message="解释本章",
        ),
        "restart:chat",
    )
    execute()
    preferences = NotePreferences(detail="concise")
    study.save_preferences(task_id, preferences, expected_revision=0)
    study.enqueue(
        task_id,
        ReviseNotesRequest(
            transcript_snapshot_id=state.transcript_snapshot_id,
            base_revision_id=state.notes_revision_id,
            preferences=preferences,
            instruction="改成提纲",
        ),
        "restart:draft",
    )
    draft = execute().output.notes_revision_id
    state = study.publish_notes(task_id, draft, expected_current_id=state.notes_revision_id)
    study.enqueue(
        task_id,
        GenerateQuizRequest(
            transcript_snapshot_id=state.transcript_snapshot_id, notes_revision_id=draft
        ),
        "restart:quiz",
    )
    quiz_op = execute()
    # Simulate stopping after the immutable batch was published, before success was durable.
    quiz_op.status = "failed"
    quiz_op.error = ErrorInfo(code="WORKER_INTERRUPTED", message="测试中断", retryable=True)
    with repo.engine.begin() as connection:
        connection.execute(
            update(OperationRow)
            .where(OperationRow.id == str(quiz_op.id))
            .values(status="failed", payload=quiz_op.model_dump(mode="json"))
        )
    study.retry(task_id, quiz_op.id)
    resumed_model = ScriptedStudyModel()
    resumed = execute(resumed_model)
    assert (
        not resumed_model.requests and resumed.output.quiz_batch_id == quiz_op.output.quiz_batch_id
    )
    assert len(resumed.attempts) == 1
    state = study.state(task_id)
    saved_result = request(application, "GET", f"/api/tasks/{task_id}/result").json()
    saved_messages = [m.model_dump(mode="json") for m in study.messages(task_id, conversation.id)]
    repo.engine.dispose()
    restarted = create_app(application.state.settings)
    try:
        assert request(
            restarted, "GET", f"/api/tasks/{task_id}/study-state"
        ).json() == state.model_dump(mode="json")
        assert request(restarted, "GET", f"/api/tasks/{task_id}/result").json() == saved_result
        assert len(request(restarted, "GET", f"/api/tasks/{task_id}/quiz-batches").json()) == 2
        assert (
            request(
                restarted, "GET", f"/api/tasks/{task_id}/conversations/{conversation.id}/messages"
            ).json()
            == saved_messages
        )
        assert (
            request(restarted, "GET", f"/api/tasks/{task_id}/note-preferences").json()[
                "preferences"
            ]["detail"]
            == "concise"
        )
    finally:
        restarted.state.repository.engine.dispose()
