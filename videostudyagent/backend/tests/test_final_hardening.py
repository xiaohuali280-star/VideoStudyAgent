import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete

from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import StudyError
from app.db.models import ArtifactRow
from app.main import create_app
from app.providers.asr import LocalWhisper
from app.services.cleanup import cleanup_temporary
from app.services.storage import ArtifactStore
from app.services.subtitles import parse_subtitles
from app.task_runner import run_task
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_exports import finished
from tests.test_upload_persistence import upload


@pytest.mark.parametrize("language,expected", [("zh-CN", "zh"), ("en-US", "en"), (None, None)])
def test_asr_normalizes_bcp47_at_provider_boundary(tmp_path, language, expected):
    (tmp_path / "model.bin").write_bytes(b"test")
    received = {}

    def transcribe(path, **options):
        received.update(options)
        return [SimpleNamespace(start=0, end=1, text="lesson")], SimpleNamespace(
            language="en", duration=1
        )

    adapter = LocalWhisper(
        Settings(_env_file=None, asr_model_path=tmp_path),
        lambda **kwargs: SimpleNamespace(transcribe=transcribe),
    )
    adapter.transcribe(tmp_path / "audio.wav", language)
    assert received["language"] == expected


@pytest.mark.parametrize(
    "bad",
    [
        "00:99.000 --> 00:99.500\nbad minutes",
        "00:03.000 --> 00:04.000\n",  # Library otherwise silently drops an empty cue.
    ],
)
def test_vtt_does_not_silently_drop_bad_cues(tmp_path, bad):
    path = tmp_path / "lesson.vtt"
    path.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nvalid\n\n" + bad)
    with pytest.raises(StudyError, match="INVALID_SUBTITLE"):
        parse_subtitles(path, "en", 10000)


def test_missing_artifact_index_requires_explicit_retry(application):
    task_id, _ = finished(application)
    repo = application.state.repository
    with repo.engine.begin() as connection:
        connection.execute(
            delete(ArtifactRow).where(ArtifactRow.task_id == task_id, ArtifactRow.kind == "quiz")
        )
    assert request(application, "GET", f"/api/tasks/{task_id}/result").status_code == 409
    assert repo.get(task_id).status == "succeeded"  # GET remains read-only.
    assert request(application, "POST", f"/api/tasks/{task_id}/retry").status_code == 202
    asyncio.run(run_task(repo.claim_next(), application.state.settings, repo, ScriptedStudyModel()))
    assert repo.get(task_id).status == "succeeded"


def test_cleanup_preserves_inputs_results_recent_files_and_active_tasks(application):
    task_id, _ = finished(application)
    repo, settings = application.state.repository, application.state.settings
    active = upload(application).json()["id"]
    root = settings.data_dir
    files = [
        root / "tasks" / task_id / "tmp" / "audio.wav",
        root / "tasks" / task_id / "exports" / "stale.tmp",
        root / "tasks" / task_id / "tmp" / "recent.tmp",
        root / "tasks" / task_id / "tmp" / "unknown.txt",
        root / "tasks" / active / "inputs" / "active.part",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"temporary")
        os.utime(path, (0, 0))
    os.utime(files[2], (10000, 10000))
    assert cleanup_temporary(settings, repo, now=10001) == 2
    assert all(path.exists() for path in files[2:])
    store = ArtifactStore(root, repo)
    assert all(
        store.verify(item).is_file() for item in [*repo.assets(task_id), *repo.artifacts(task_id)]
    )


def test_cleanup_does_not_follow_directory_links(application, tmp_path):
    task_id, _ = finished(application)
    outside = tmp_path / "outside"
    outside.mkdir()
    file = outside / "outside.tmp"
    file.write_text("keep")
    os.utime(file, (0, 0))
    link = application.state.settings.data_dir / "tasks" / task_id / "exports"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Directory links unavailable")
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True
        )
        assert result.returncode == 0
    assert cleanup_temporary(application.state.settings, application.state.repository) == 0
    assert file.exists()


def test_adopted_source_manifest_matches_local_files_and_licenses():
    records = json.loads((PROJECT_ROOT / "docs/UPSTREAM_SOURCES.json").read_text("utf-8"))[
        "adoptions"
    ]
    assert {item["id"] for item in records} == {"B1", "B2", "B3", "B4", "D1", "D2", "D3", "T1"}
    for item in records:
        assert len(item["commit"]) == 40 and item["status"] == "adopted"
        assert item["license"] in {"MIT", "Apache-2.0"}
        assert item["sources"] and item["tests"] and item["changes"]
        for local in item["local_files"]:
            path = (PROJECT_ROOT / local["path"]).resolve()
            assert path.is_relative_to(PROJECT_ROOT.resolve())
            content = path.read_bytes().replace(b"\r\n", b"\n")
            assert hashlib.sha256(content).hexdigest() == local["sha256"], local["path"]
    for license in ("BiliNote-MIT.txt", "DeepTutor-Apache-2.0.txt", "AI-Tutor-MIT.txt"):
        assert (PROJECT_ROOT / "third_party/licenses" / license).stat().st_size > 500


@pytest.mark.parametrize("content_length", [False, True])
def test_cumulative_upload_limit_with_or_without_content_length(tmp_path, content_length):
    app = create_app(
        Settings(_env_file=None, data_dir=tmp_path, max_video_bytes=1, max_subtitle_bytes=1)
    )

    async def send():
        async def stream():
            yield b'--b\r\nContent-Disposition: form-data; name="video"; filename="x.mp4"\r\n\r\n'
            for _ in range(10):
                yield b"x" * 10000
            yield b"\r\n--b--\r\n"

        headers = {"Content-Type": "multipart/form-data; boundary=b"}
        if content_length:
            headers["Content-Length"] = "100100"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/api/tasks", content=stream(), headers=headers)

    response = asyncio.run(send())
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"
    assert not hasattr(app.state, "repository")
