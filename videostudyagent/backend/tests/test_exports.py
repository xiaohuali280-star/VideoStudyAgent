import asyncio
from uuid import uuid4

import pytest

from app.services.exports import FORMATS
from app.services.transcription import TranscriptService
from app.task_runner import run_task
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_upload_persistence import MP4, upload


def finished(application):
    response = upload(application)
    repo = application.state.repository
    task = repo.claim_next()
    model = ScriptedStudyModel()
    asyncio.run(run_task(task, application.state.settings, repo, model))
    assert repo.get(task.id).status == "succeeded"
    return response.json()["id"], model


@pytest.mark.parametrize("format", sorted(FORMATS))
def test_downloads_match_results_and_do_not_generate(application, format):
    task_id, model = finished(application)
    calls = len(model.requests)
    path = f"/api/tasks/{task_id}/exports/{format}"
    response = request(application, "GET", path)
    assert response.status_code == 200
    assert f'filename="{format}"' in response.headers["content-disposition"]
    result = request(application, "GET", f"/api/tasks/{task_id}/result").json()
    if format.endswith(".json"):
        assert response.json() == result["quiz" if format == "quiz.json" else "transcript"]
    elif format == "transcript.srt":
        assert "00:00:00,000 --> 00:00:02,000" in response.text
        assert result["transcript"]["segments"][0]["text"] in response.text
    elif format == "quiz.md":
        assert result["quiz"]["questions"][0]["answer"] in response.text
        assert result["quiz"]["questions"][0]["explanation"] in response.text
    else:
        assert result["notes"]["title"] in response.text
        assert "00:00:00–00:00:02" in response.text
    assert request(application, "GET", path).content == response.content
    assert len(model.requests) == calls


def test_unready_partial_and_unknown_exports(application):
    task_id = upload(application).json()["id"]
    assert request(application, "GET", f"/api/tasks/{task_id}/exports/notes.md").status_code == 409
    assert (
        request(application, "GET", f"/api/tasks/{task_id}/exports/secret.txt").status_code == 404
    )
    assert request(application, "GET", f"/api/tasks/{uuid4()}/result").status_code == 404
    repo = application.state.repository
    TranscriptService(application.state.settings, repo).load_subtitles(repo.get(task_id))
    partial = request(application, "GET", f"/api/tasks/{task_id}/result")
    assert partial.status_code == 200 and partial.json()["notes"] is None
    assert partial.json()["transcript"] is not None
    assert "storage_key" not in partial.text and "app.db" not in partial.text
    assert (
        request(application, "GET", f"/api/tasks/{task_id}/exports/transcript.srt").status_code
        == 200
    )


def test_corrupt_completed_result_can_be_explicitly_retried(application):
    task_id, _ = finished(application)
    repo = application.state.repository
    quiz = next(a for a in repo.artifacts(task_id) if a.kind == "quiz")
    store = TranscriptService(application.state.settings, repo).store
    store.path(quiz.storage_key).write_bytes(b"corrupt")
    assert request(application, "GET", f"/api/tasks/{task_id}/result").status_code == 409
    assert request(application, "POST", f"/api/tasks/{task_id}/retry").status_code == 202
    assert repo.get(task_id).attempt == 2
    task = repo.claim_next()
    asyncio.run(run_task(task, application.state.settings, repo, ScriptedStudyModel()))
    assert repo.get(task_id).status == "succeeded"


def test_healthy_successful_task_cannot_be_retried(application):
    task_id, _ = finished(application)
    assert request(application, "POST", f"/api/tasks/{task_id}/retry").status_code == 409


def test_video_is_task_bound_and_supports_range(application):
    task_id = upload(application, {"video": ("course.mp4", MP4)}).json()["id"]
    response = request(
        application, "GET", f"/api/tasks/{task_id}/video", headers={"Range": "bytes=0-7"}
    )
    assert response.status_code == 206 and response.content == MP4[:8]
    assert response.headers["content-type"] == "video/mp4"
    subtitle_task = upload(application).json()["id"]
    assert request(application, "GET", f"/api/tasks/{subtitle_task}/video").status_code == 404
    assert request(application, "GET", f"/api/tasks/{uuid4()}/video").status_code == 404


def test_public_config_contains_only_limits_and_formats(application):
    response = request(application, "GET", "/api/config")
    assert response.status_code == 200
    assert set(response.json()) == {
        "schema_version",
        "max_video_bytes",
        "max_subtitle_bytes",
        "max_duration_ms",
        "export_formats",
    }
    assert set(response.json()["export_formats"]) == FORMATS
    assert not application.state.settings.data_dir.exists()
