import asyncio
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from app.db.repository import now
from app.db.study_repository import StudyRepository
from app.operation_worker import OperationWorker
from app.providers.fakes import FakeLLM
from app.schemas.iteration import NotesRevision
from app.schemas.providers import ModelReply
from app.schemas.study import NotesDocument
from app.services.operations import VersionWriter, run_operation
from app.services.study_versions import VersionReader
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def test_partial_revision_keeps_unselected_chapter_exactly(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    model = ScriptedStudyModel()
    asyncio.run(run_operation(study.claim_next(), application.state.settings, repo, model))
    state = study.state(task_id)
    original = VersionReader(application.state.settings.data_dir).notes(
        study.notes(task_id, state.notes_revision_id)
    )
    first = original.chapters[0].model_copy(update={"id": "chapter_one"})
    second = original.chapters[0].model_copy(
        update={"id": "chapter_two", "content_markdown": "保留原样：学习率决定步长。"}
    )
    document = NotesDocument.model_validate(
        original.model_dump() | {"chapters": [first.model_dump(), second.model_dump()]}
    )
    record = study.add_notes(
        NotesRevision(
            id=uuid4(),
            task_id=task_id,
            transcript_snapshot_id=state.transcript_snapshot_id,
            parent_revision_id=state.notes_revision_id,
            document_schema_version="1.0",
            created_at=now(),
            **VersionWriter(application.state.settings.data_dir).write(task_id, "notes", document),
        )
    )
    study.publish_notes(task_id, record.id, expected_current_id=state.notes_revision_id)
    response = request(
        application,
        "POST",
        f"/api/tasks/{task_id}/operations",
        headers={"Idempotency-Key": "partial"},
        json={
            "kind": "revise_notes",
            "base_revision_id": str(record.id),
            "transcript_snapshot_id": str(state.transcript_snapshot_id),
            "chapter_ids": [first.id],
            "preferences": {"detail": "concise"},
            "instruction": "用提纲表达",
        },
    )
    assert response.status_code == 202
    op = study.claim_next()
    asyncio.run(run_operation(op, application.state.settings, repo, model))
    completed = study.operation(task_id, op.id)
    assert completed.status == "succeeded", completed.error
    draft = VersionReader(application.state.settings.data_dir).notes(
        study.notes(task_id, completed.output.notes_revision_id)
    )
    assert draft.chapters[1].model_dump() == second.model_dump()
    assert draft.chapters[0].source_segment_ids == first.source_segment_ids
    assert study.state(task_id).notes_revision_id == record.id


def test_chat_rejects_forged_role_invalid_citations_and_oversized_context(application):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    asyncio.run(
        run_operation(study.claim_next(), application.state.settings, repo, ScriptedStudyModel())
    )
    state = study.state(task_id)
    conversation = study.create_conversation(task_id)
    notes = VersionReader(application.state.settings.data_dir).notes(
        study.notes(task_id, state.notes_revision_id)
    )
    body = {
        "kind": "chat_reply",
        "conversation_id": str(conversation.id),
        "notes_revision_id": str(state.notes_revision_id),
        "chapter_ids": [notes.chapters[0].id],
        "message": "解释笔记",
    }
    url = f"/api/tasks/{task_id}/operations"
    assert (
        request(
            application,
            "POST",
            url,
            headers={"Idempotency-Key": "forged"},
            json=body | {"role": "system"},
        ).status_code
        == 422
    )
    assert (
        request(application, "POST", url, headers={"Idempotency-Key": "bad"}, json=body).status_code
        == 202
    )
    bad = ModelReply(
        content=json.dumps(
            {
                "answer_markdown": "不可靠回答",
                "citations": [{"segment_id": "invented", "quote": "fabricated"}],
            }
        )
    )
    fake = FakeLLM([bad, bad])
    op = study.claim_next()
    asyncio.run(run_operation(op, application.state.settings, repo, fake))
    assert study.operation(task_id, op.id).error.code == "GENERATION_INVALID"
    assert len(fake.requests) == 2
    assert [m.role for m in study.messages(task_id, conversation.id)] == ["user"]
    assert (
        request(
            application, "POST", url, headers={"Idempotency-Key": "too-large"}, json=body
        ).status_code
        == 202
    )
    op = study.claim_next()
    model = ScriptedStudyModel()
    asyncio.run(
        run_operation(
            op, application.state.settings.model_copy(update={"llm_context_tokens": 1}), repo, model
        )
    )
    assert study.operation(task_id, op.id).error.code == "CONTEXT_LIMIT"
    assert not model.requests
    assert study.state(task_id) == state


def test_cancel_running_operation_terminates_owned_child(application, tmp_path, monkeypatch):
    task_id = upload(application).json()["id"]
    repo = application.state.repository
    study = StudyRepository(repo.engine)
    operation = study.operations(task_id)[0]
    marker = tmp_path / "child.pid"
    original = subprocess.Popen
    script = (
        "import subprocess,sys,time; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
    )

    def launch(args, **kwargs):
        if "app.operation_runner" in args:
            args = [sys.executable, "-c", script, str(marker)]
        return original(args, **kwargs)

    monkeypatch.setattr("app.operation_worker.subprocess.Popen", launch)
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(OperationWorker(application.state.settings, repo).run_once)
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        study.request_cancel(task_id, operation.id)
        assert work.result(timeout=15)
    assert study.operation(task_id, operation.id).status == "cancelled"
    assert repo.get(task_id).status == "failed"
    pid = marker.read_text().strip()
    if os.name == "nt":
        output = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=10,
        )
        assert f'"{pid}"'.encode() not in output.stdout
    else:
        output = subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, timeout=10)
        assert not output.stdout.strip() or output.stdout.strip().startswith(b"Z")
