import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.db.repository import TaskRepository, initialize_database
from app.main import create_app
from app.schemas.common import ErrorInfo
from app.schemas.tasks import TaskStep
from tests.test_config_health import request

SRT = b"1\n00:00:00,000 --> 00:00:02,000\nLearning rate controls step size.\n"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\0" * 20


def upload(app, files=None, **kwargs):
    if files is None:
        files = {"subtitle": ("lesson.srt", SRT)}
    return request(app, "POST", "/api/tasks", files=files, **kwargs)


@pytest.mark.parametrize(
    "files",
    [
        {"video": ("course.mp4", MP4)},
        {"subtitle": ("course.srt", SRT)},
        {"video": ("course.mp4", MP4), "subtitle": ("course.srt", SRT)},
    ],
)
def test_input_combinations_survive_api_restart(application, files):
    response = upload(application, files, data={"options": json.dumps({"question_count": 5})})
    assert response.status_code == 202, response.text
    task = response.json()
    assert task["status"] == "queued" and task["options"]["question_count"] == 5
    repo = application.state.repository
    assert len(repo.assets(task["id"])) == len(files)
    repo.engine.dispose()
    restarted = create_app(application.state.settings)
    try:
        detail = request(restarted, "GET", f"/api/tasks/{task['id']}")
        assert detail.status_code == 200
        assert detail.json()["task"] == task
        assert "storage_key" not in detail.text
        assert request(restarted, "GET", "/api/tasks").json() == [task]
    finally:
        restarted.state.repository.engine.dispose()


@pytest.mark.parametrize(
    ("files", "data", "status"),
    [
        ({}, {}, 422),
        ({"video": ("wrong.mp4", b"not video")}, {}, 415),
        ({"video": ("wrong.exe", MP4)}, {}, 415),
        ({"subtitle": ("wrong.srt", b"no timestamps")}, {}, 415),
        ({"subtitle": ("empty.srt", b"")}, {}, 422),
        ({"subtitle": ("lesson.srt", SRT)}, {"options": '{"question_count": 21}'}, 422),
        ({"subtitle": ("lesson.srt", SRT)}, {"options": '{"difficulty": "invalid"}'}, 422),
        ({"subtitle": ("lesson.srt", SRT)}, {"options": "not json"}, 422),
        ([("subtitle", ("a.srt", SRT)), ("subtitle", ("b.srt", SRT))], {}, 422),
    ],
)
def test_upload_errors_leave_no_inputs(application, files, data, status):
    response = upload(application, files, data=data)
    assert response.status_code == status, response.text
    assert "error" in response.json()
    tasks_dir = application.state.settings.data_dir / "tasks"
    assert not tasks_dir.exists() or not list(tasks_dir.iterdir())


def test_size_limit_cleans_partial_upload(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, max_subtitle_bytes=10))
    try:
        assert upload(app).status_code == 413
        assert not list((tmp_path / "tasks").iterdir())
    finally:
        app.state.repository.engine.dispose()


def test_filename_cannot_control_storage_path(application):
    response = upload(application, {"subtitle": ("../../outside.srt", SRT)})
    assert response.status_code == 202
    asset = application.state.repository.assets(response.json()["id"])[0]
    assert asset.original_name == "outside.srt"
    root = application.state.settings.data_dir.resolve()
    assert (root / asset.storage_key).resolve().is_relative_to(root)
    assert not (root.parent / "outside.srt").exists()


def test_atomic_claim_retry_and_previous_steps(application):
    task = upload(application).json()
    repo = application.state.repository
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: repo.claim_next(), range(2)))
    assert sum(item is not None for item in claims) == 1
    step = TaskStep(id=uuid4(), task_id=task["id"], attempt=1, tool_name="load_subtitles")
    repo.save_step(step)
    repo.finish(task["id"], ErrorInfo(code="WORKER_INTERRUPTED", message="中断", retryable=True))
    response = request(application, "POST", f"/api/tasks/{task['id']}/retry")
    assert response.status_code == 202
    assert response.json()["attempt"] == 2
    assert response.json()["status"] == "queued"
    assert len(repo.detail(task["id"]).steps) == 1
    assert request(application, "POST", f"/api/tasks/{task['id']}/retry").status_code == 409


def test_nonretryable_and_unknown_tasks(application):
    task = upload(application).json()
    repo = application.state.repository
    repo.claim_next()
    repo.finish(task["id"], ErrorInfo(code="INVALID_SUBTITLE", message="无效"))
    assert request(application, "POST", f"/api/tasks/{task['id']}/retry").status_code == 409
    assert request(application, "GET", f"/api/tasks/{uuid4()}").status_code == 404
    assert request(application, "GET", "/api/tasks/not-a-uuid").status_code == 422
    assert request(application, "GET", "/api/tasks?limit=101").status_code == 422


def test_foreign_keys_prevent_orphan_inputs(tmp_path):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from app.db.models import AssetRow

    repo = TaskRepository(initialize_database(tmp_path / "test.db"))
    try:
        with pytest.raises(IntegrityError), repo.engine.begin() as conn:
            conn.execute(
                insert(AssetRow).values(
                    id=str(uuid4()),
                    task_id=str(uuid4()),
                    kind="video",
                    payload={},
                )
            )
    finally:
        repo.engine.dispose()
