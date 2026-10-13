import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from filelock import Timeout

from app.core.config import Settings
from app.core.locking import native_lock
from app.db.repository import TaskRepository, initialize_database
from app.schemas.common import ErrorInfo
from app.services.cleanup import cleanup_temporary


def kill_attempt(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


class Worker:
    def __init__(self, settings: Settings, repository: TaskRepository, runner=None):
        self.settings, self.repository = settings, repository
        self.runner = runner or self.spawn_attempt

    def spawn_attempt(self, task, command=None):
        command = command or [sys.executable, "-m", "app.task_runner", "--task-id", str(task.id)]
        environment = os.environ.copy()
        environment["VSA_DATA_DIR"] = str(self.settings.data_dir)
        # Only non-secret runtime overrides; keys stay in inherited environment/local .env.
        for field in (
            "asr_model",
            "asr_device",
            "asr_compute_type",
            "asr_cpu_threads",
            "asr_timeout",
            "media_probe_timeout",
            "media_extract_timeout",
            "max_duration_ms",
            "subtitle_tolerance_ms",
            "llm_model",
            "llm_base_url",
            "llm_timeout",
            "llm_context_tokens",
            "llm_max_output_tokens",
            "llm_max_request_bytes",
            "llm_max_requests",
            "llm_total_tokens",
            "agent_max_tool_calls",
            "agent_max_no_progress",
            "ffmpeg_binary",
            "ffprobe_binary",
        ):
            value = getattr(self.settings, field)
            if value is not None:
                environment["VSA_" + field.upper()] = str(value)
        if self.settings.asr_model_path:
            environment["VSA_ASR_MODEL_PATH"] = str(self.settings.asr_model_path)
        process = subprocess.Popen(
            command,
            env=environment,
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        try:
            process.wait(timeout=self.settings.task_timeout)
        except subprocess.TimeoutExpired:
            kill_attempt(process)
            self.repository.finish(
                task.id, ErrorInfo(code="TASK_TIMEOUT", message="任务超过总时限。", retryable=True)
            )
        except KeyboardInterrupt:
            kill_attempt(process)
            self.repository.finish(
                task.id,
                ErrorInfo(code="WORKER_INTERRUPTED", message="任务已中断。", retryable=True),
            )
            raise
        finally:
            if process.poll() is None:
                kill_attempt(process)
        if self.repository.get(task.id).status == "running":
            self.repository.finish(
                task.id,
                ErrorInfo(
                    code="WORKER_INTERRUPTED", message="执行进程未正常完成。", retryable=True
                ),
            )

    def run_once(self):
        task = self.repository.claim_next()
        if task is None:
            return False
        try:
            self.runner(task)
        except KeyboardInterrupt:
            raise
        except Exception:
            if self.repository.get(task.id).status == "running":
                self.repository.finish(
                    task.id,
                    ErrorInfo(
                        code="WORKER_INTERRUPTED", message="执行进程未完成。", retryable=True
                    ),
                )
        return True


def main():
    parser = argparse.ArgumentParser(description="Single local VideoStudyAgent Worker")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    lock = native_lock(settings.data_dir / ".worker.lock")
    try:
        with lock.acquire(timeout=0):
            repository = TaskRepository(initialize_database(settings.data_dir / "app.db"))
            try:
                repository.recover_interrupted()
                cleanup_temporary(settings, repository)
                worker = Worker(settings, repository)
                while True:
                    processed = worker.run_once()
                    if args.once:
                        return 0
                    if not processed:
                        time.sleep(settings.worker_poll_interval)
            finally:
                repository.engine.dispose()
    except Timeout:
        print("WORKER_ALREADY_RUNNING")
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
