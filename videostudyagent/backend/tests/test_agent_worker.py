import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest

from app.adapters.tool_args import missing_args_message, unsatisfied_required_args
from app.agent.tools import StudyTools
from app.core.errors import StudyError
from app.core.locking import native_lock
from app.main import create_app
from app.providers.fakes import FakeASR, FakeLLM
from app.schemas.common import ErrorInfo
from app.schemas.providers import ModelReply, ToolCall, ToolDefinition
from app.schemas.study import Transcript
from app.schemas.tasks import TaskStep
from app.services.transcription import TranscriptService
from app.task_runner import run_task
from app.worker import Worker
from tests.scripted_llm import ScriptedStudyModel
from tests.test_config_health import request
from tests.test_transcription import real_video as media_fixture
from tests.test_upload_persistence import upload

real_video = media_fixture


def execute(application, model, asr=None):
    repo, settings = application.state.repository, application.state.settings
    worker = Worker(
        settings,
        repo,
        lambda task: asyncio.run(
            run_task(task, settings, repo, model, asr),
        ),
    )
    assert worker.run_once()
    return repo


def test_single_agent_subtitle_path_and_audit(application):
    task = upload(application).json()
    repo = execute(application, ScriptedStudyModel())
    assert repo.get(task["id"]).status == "succeeded"
    steps = repo.detail(task["id"]).steps
    assert [step.tool_name for step in steps] == [
        "load_subtitles",
        "generate_notes",
        "generate_quiz",
    ]
    assert all(step.status == "succeeded" and step.duration_ms is not None for step in steps)
    assert [step.sequence for step in steps] == [1, 2, 3]
    assert not Worker(application.state.settings, repo).run_once()


def test_single_agent_video_path_with_real_media_fake_asr(application, real_video):
    task = upload(application, {"video": ("course.mp4", real_video.read_bytes())}).json()
    asr = FakeASR(
        Transcript(
            source="asr",
            language="en",
            duration_ms=2000,
            segments=[
                {
                    "id": "seg_1",
                    "start_ms": 0,
                    "end_ms": 2000,
                    "text": "Learning rate controls step size.",
                },
            ],
        )
    )
    repo = execute(application, ScriptedStudyModel(), asr)
    assert repo.get(task["id"]).status == "succeeded"
    assert [step.tool_name for step in repo.detail(task["id"]).steps] == [
        "extract_audio",
        "transcribe_audio",
        "generate_notes",
        "generate_quiz",
    ]
    assert len(asr.calls) == 1


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("run_shell", {"command": "do not execute"}),
        ("load_subtitles", {"path": "../../outside"}),
        ("generate_notes", {}),
    ],
)
def test_one_invalid_call_can_be_corrected(application, name, args):
    task = upload(application).json()

    class CorrectingModel(ScriptedStudyModel):
        def __init__(self):
            super().__init__()
            self.first = True

        async def complete(self, req):
            if self.first:
                self.first = False
                return ModelReply(
                    tool_calls=[ToolCall(id="invalid_call", name=name, arguments=args)]
                )
            return await super().complete(req)

    repo = execute(application, CorrectingModel())
    assert repo.get(task["id"]).status == "succeeded"
    assert repo.detail(task["id"]).steps[0].status == "failed"
    assert len(repo.detail(task["id"]).steps) == 4


def test_two_invalid_calls_fail_without_running_unknown_tools(application):
    task = upload(application).json()
    model = FakeLLM(
        [
            ModelReply(tool_calls=[ToolCall(id=f"bad_{i}", name="unknown", arguments={})])
            for i in range(2)
        ]
    )
    repo = execute(application, model)
    assert repo.get(task["id"]).error.code == "AGENT_INVALID_CALL"
    assert not repo.artifacts(task["id"])
    assert [s.tool_name for s in repo.detail(task["id"]).steps] == ["unknown", "unknown"]
    assert any(
        m.role == "tool" and not json.loads(m.content)["ok"] for m in model.requests[1].messages
    )


def test_premature_finish_does_not_mark_success(application):
    task = upload(application).json()
    repo = execute(application, FakeLLM([ModelReply(content="done"), ModelReply(content="done")]))
    assert repo.get(task["id"]).status == "failed"
    assert repo.get(task["id"]).error.code == "AGENT_INCOMPLETE"


def test_repeated_calls_are_idempotent_and_bounded(application):
    task = upload(application).json()
    model = FakeLLM(
        [
            ModelReply(tool_calls=[ToolCall(id=f"repeat_{i}", name="load_subtitles", arguments={})])
            for i in range(4)
        ]
    )
    repo = execute(application, model)
    assert repo.get(task["id"]).error.code == "AGENT_LIMIT_EXCEEDED"
    assert len(repo.artifacts(task["id"])) == 1
    assert [s.status for s in repo.detail(task["id"]).steps] == [
        "succeeded",
        "skipped",
        "skipped",
        "skipped",
    ]


def test_tool_call_limit_is_enforced(application):
    application.state.settings.agent_max_tool_calls = 1
    task = upload(application).json()
    repo = execute(application, ScriptedStudyModel())
    assert repo.get(task["id"]).error.code == "AGENT_LIMIT_EXCEEDED"
    assert len(repo.artifacts(task["id"])) == 1


def test_artifact_ids_cannot_cross_tasks(application):
    first = upload(application).json()
    second = upload(application).json()
    repo = application.state.repository
    service = TranscriptService(application.state.settings, repo)
    service.load_subtitles(repo.get(first["id"]))
    foreign = service.load_subtitles(repo.get(second["id"]))
    task = repo.claim_next()
    tools = StudyTools(task, application.state.settings, repo, ScriptedStudyModel())
    with pytest.raises(StudyError, match="TOOL_FORBIDDEN"):
        asyncio.run(
            tools.execute(
                ToolCall(
                    id="cross",
                    name="generate_notes",
                    arguments={"transcript_artifact_id": str(foreign.id)},
                ),
                1,
            )
        )
    assert not any(a.kind == "notes" for a in repo.artifacts(task.id))


def test_d3_missing_blank_default_and_empty_collection_semantics():
    definition = ToolDefinition(
        name="test",
        description="test",
        parameters={
            "type": "object",
            "required": ["a", "b", "c", "d"],
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "array"},
                "c": {"type": "integer", "default": 1},
                "d": {"type": "string"},
            },
        },
    )
    absent, blank = unsatisfied_required_args(definition, {"a": " ", "b": [], "d": None})
    assert [a.name for a in absent] == ["d"]
    assert [a.name for a in blank] == ["a"]
    message = missing_args_message("test", absent, blank)
    assert "Missing" in message and "blank" in message and "Call not dispatched" in message


def test_recovery_is_explicit_and_preserves_completed_artifacts(application):
    first = upload(application).json()
    queued = upload(application).json()
    repo = application.state.repository
    task = repo.claim_next()
    artifact = TranscriptService(application.state.settings, repo).load_subtitles(task)
    repo.save_step(
        TaskStep(
            id=uuid4(),
            task_id=task.id,
            attempt=1,
            tool_name="generate_notes",
            status="running",
            sequence=1,
        )
    )
    restarted = create_app(application.state.settings)
    detail = request(restarted, "GET", f"/api/tasks/{task.id}")
    assert detail.json()["task"]["status"] == "running"
    restarted.state.repository.engine.dispose()
    with native_lock(application.state.settings.data_dir / ".worker.lock").acquire():
        repo.recover_interrupted()
    assert repo.get(task.id).error.code == "WORKER_INTERRUPTED"
    assert repo.detail(task.id).steps[0].status == "failed"
    assert repo.get(queued["id"]).status == "queued"
    repo.retry(first["id"])
    assert repo.get(first["id"]).attempt == 2
    assert repo.artifacts(first["id"])[0].id == artifact.id


def test_native_worker_lock_is_exclusive_and_released_after_crash(tmp_path):
    lock_path = tmp_path / ".worker.lock"
    script = """from app.core.locking import native_lock
from filelock import Timeout
import sys
try:
    with native_lock(sys.argv[1]).acquire(timeout=0):
        print('acquired')
except Timeout:
    print('blocked')
"""
    with native_lock(lock_path).acquire():
        result = subprocess.run(
            [sys.executable, "-c", script, str(lock_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "blocked"
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.locking import native_lock; "
            "import os,sys; lock=native_lock(sys.argv[1]); "
            "lock.acquire(timeout=0); os._exit(0)",
            str(lock_path),
        ],
        capture_output=True,
        timeout=10,
    )
    assert crashed.returncode == 0
    with native_lock(lock_path).acquire(timeout=0):
        pass


def test_total_timeout_kills_owned_attempt_and_child(application, tmp_path):
    task = upload(application).json()
    repo = application.state.repository
    task = repo.claim_next()
    application.state.settings.task_timeout = 1
    pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,time; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)']); "
        "Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(15)"
    )
    Worker(application.state.settings, repo).spawn_attempt(
        task, [sys.executable, "-c", script, str(pid_file)]
    )
    assert repo.get(task.id).error.code == "TASK_TIMEOUT"
    child_pid = pid_file.read_text().strip()
    if os.name == "nt":
        check = subprocess.run(
            ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            timeout=10,
        )
        assert f'"{child_pid}"'.encode() not in check.stdout
    else:
        check = subprocess.run(
            ["ps", "-o", "stat=", "-p", child_pid], capture_output=True, timeout=10
        )
        assert not check.stdout.strip() or check.stdout.strip().startswith(b"Z")


def test_api_remains_available_while_worker_is_busy(application):
    upload(application)
    started, finished = Event(), Event()
    repo = application.state.repository

    def runner(task):
        started.set()
        assert finished.wait(10)
        repo.finish(
            task.id, ErrorInfo(code="WORKER_INTERRUPTED", message="测试结束", retryable=True)
        )

    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(Worker(application.state.settings, repo, runner).run_once)
        try:
            assert started.wait(5)
            assert request(application, "GET", "/api/health").status_code == 200
            assert request(application, "GET", "/api/tasks").json()[0]["status"] == "running"
        finally:
            finished.set()
        assert work.result(timeout=5)
