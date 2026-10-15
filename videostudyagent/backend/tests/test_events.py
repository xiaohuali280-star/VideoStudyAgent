import asyncio
import json
from uuid import uuid4

import pytest

from app.db.event_repository import EventRepository
from app.db.session import create_database_engine
from app.db.study_repository import StudyRepository
from app.routes.events import stream_events
from app.schemas.common import ErrorInfo
from tests.test_config_health import request
from tests.test_upload_persistence import upload


def setup(application):
    response = upload(application)
    assert response.status_code == 202
    task_id = response.json()["id"]
    engine = application.state.repository.engine
    study, events = StudyRepository(engine), EventRepository(engine)
    return task_id, study, events, study.operations(task_id)[0]


def payload(frame):
    return json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))


def test_state_and_event_atomic_rollback(application, monkeypatch):
    task_id, study, events, operation = setup(application)
    assert len(events.after(task_id, 0)) == 1

    def rejected(*args, **kwargs):
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr("app.db.event_repository.append_event", rejected)
    with pytest.raises(RuntimeError):
        study.claim_next()
    assert study.operation(task_id, operation.id).status == "queued"
    assert study.operation(task_id, operation.id).event_revision == 0
    assert len(events.after(task_id, 0)) == 1


def test_snapshot_cursor_same_read_transaction_and_no_registration_gap(application, monkeypatch):
    task_id, study, events, operation = setup(application)
    original = events._state

    def during_read(connection, task):
        study.claim_next()  # A different writer commits after the cursor SELECT.
        return original(connection, task)

    monkeypatch.setattr(events, "_state", during_read)
    snapshot = events.snapshot(task_id, operation.id)
    assert snapshot.operations[0].status == "queued"
    after = events.after(task_id, snapshot.cursor)
    assert [event.status for event in after] == ["running"]
    assert after[0].state_revision > snapshot.operations[0].event_revision


def test_subscribe_before_finish_and_terminal_stream_closes(application):
    task_id, study, events, operation = setup(application)
    initial = events.snapshot(task_id, operation.id)
    study.claim_next()
    study.finish(
        task_id,
        operation.id,
        error=ErrorInfo(code="TEST_STOP", message="self-created", retryable=True),
    )

    async def consume():
        stream = stream_events(events, task_id, initial, operation_id=operation.id, poll=0)
        return [frame async for frame in stream]

    frames = asyncio.run(consume())
    assert payload(frames[0])["operations"][0]["status"] == "queued"
    assert [payload(f)["status"] for f in frames[1:]] == ["running", "failed"]


def test_completed_before_connect_resume_and_cross_engine_restart(application):
    task_id, study, events, operation = setup(application)
    queued_cursor = events.snapshot(task_id).cursor
    study.claim_next()
    study.finish(
        task_id,
        operation.id,
        error=ErrorInfo(code="TEST_STOP", message="原文不会进入事件", retryable=True),
    )
    restarted = create_database_engine(application.state.settings.data_dir / "app.db")
    try:
        reader = EventRepository(restarted)
        snapshot = reader.snapshot(task_id, operation.id)

        async def consume():
            return [
                f
                async for f in stream_events(
                    reader, task_id, snapshot, since=queued_cursor, operation_id=operation.id
                )
            ]

        frames = asyncio.run(consume())
        assert [payload(f)["status"] for f in frames[:-1]] == ["running", "failed"]
        assert payload(frames[-1])["operations"][0]["status"] == "failed"
        serialized = "".join(frames)
        assert "原文不会进入事件" not in serialized and "preferences" not in serialized
    finally:
        restarted.dispose()


def test_prune_reset_keeps_versions_and_other_courses(application):
    task_id, study, events, operation = setup(application)
    other = upload(application).json()["id"]
    before_other = events.after(other, 0)
    old = events.snapshot(task_id).cursor
    study.claim_next()
    study.progress(task_id, operation.id, "ocr", completed_units=1, total_units=2)
    study.progress(task_id, operation.id, "ocr", completed_units=2, total_units=2)
    study.finish(
        task_id, operation.id, error=ErrorInfo(code="TEST_STOP", message="test", retryable=True)
    )
    assert events.prune(task_id, keep=2) > 0
    snapshot = events.snapshot(task_id, operation.id)

    async def consume():
        return [
            f
            async for f in stream_events(
                events, task_id, snapshot, since=old, operation_id=operation.id
            )
        ]

    frames = asyncio.run(consume())
    assert "event: reset" in frames[0] and payload(frames[0])["cursor"] == snapshot.cursor
    assert events.after(other, 0) == before_other
    assert application.state.repository.get(task_id)


def test_retry_cancel_and_progress_are_ordered_metadata_only(application):
    task_id, study, events, operation = setup(application)
    study.claim_next()
    study.finish(
        task_id,
        operation.id,
        error=ErrorInfo(code="WORKER_INTERRUPTED", message="test", retryable=True),
    )
    study.retry(task_id, operation.id)
    study.claim_next()
    study.request_cancel(task_id, operation.id)
    study.acknowledge_cancel(task_id, operation.id)
    records = events.after(task_id, 0)
    assert [e.event_id for e in records] == sorted({e.event_id for e in records})
    assert [e.state_revision for e in records] == list(range(len(records)))
    assert records[-1].status == "cancelled" and records[-1].attempt == 2
    assert all(e.completed_units is None for e in records)
    assert not any("content" in e.model_dump() or "request" in e.model_dump() for e in records)


@pytest.mark.parametrize("cursor", ["-1", "abc", "١", "9007199254740992"])
def test_http_cursor_validation_and_missing_course(application, cursor):
    task_id, study, events, operation = setup(application)
    response = request(
        application,
        "GET",
        f"/api/tasks/{task_id}/events",
        headers={"Last-Event-ID": cursor.encode("utf-8")},
    )
    assert response.status_code == 422
    assert request(application, "GET", f"/api/tasks/{uuid4()}/events").status_code == 404


def test_http_completed_operation_sse_utf8_replay(application):
    task_id, study, events, operation = setup(application)
    study.request_cancel(task_id, operation.id)
    response = request(
        application, "GET", f"/api/tasks/{task_id}/events?operation_id={operation.id}&since=0"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"status": "cancelled"' in response.text and "event: snapshot" in response.text
