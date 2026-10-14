import os
import subprocess
import sys
import time
from pathlib import Path

from app.db.study_repository import StudyRepository
from app.schemas.common import ErrorInfo


class OperationWorker:
    def __init__(self, settings, repository, runner=None):
        self.settings, self.repository = settings, repository
        self.study = StudyRepository(repository.engine)
        self.runner = runner or self.spawn

    def spawn(self, operation):
        from app.worker import kill_attempt

        env = os.environ.copy()
        for name, value in self.settings.model_dump().items():
            if name in {"cors_origins"} or value is None:
                continue
            env["VSA_" + name.upper()] = str(value)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.operation_runner",
                "--task-id",
                str(operation.task_id),
                "--operation-id",
                str(operation.id),
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        started = time.monotonic()
        try:
            while process.poll() is None:
                current = self.study.operation(operation.task_id, operation.id)
                if current.cancel_requested:
                    kill_attempt(process)
                    self.study.acknowledge_cancel(operation.task_id, operation.id)
                    return
                if time.monotonic() - started > self.settings.task_timeout:
                    kill_attempt(process)
                    self.study.finish(
                        operation.task_id,
                        operation.id,
                        error=ErrorInfo(
                            code="TASK_TIMEOUT", message="操作超过总时限。", retryable=True
                        ),
                    )
                    return
                time.sleep(0.2)
        finally:
            if process.poll() is None:
                kill_attempt(process)
            current = self.study.operation(operation.task_id, operation.id)
            if current.status == "running":
                self.study.finish(
                    operation.task_id,
                    operation.id,
                    error=ErrorInfo(
                        code="WORKER_INTERRUPTED", message="操作进程已中断。", retryable=True
                    ),
                )

    def run_once(self):
        operation = self.study.claim_next()
        if operation is None:
            return False
        self.runner(operation)
        current = self.study.operation(operation.task_id, operation.id)
        if (
            operation.request.kind == "initial_study"
            and current.status in {"failed", "cancelled"}
            and self.repository.get(operation.task_id).status == "running"
        ):
            self.repository.finish(
                operation.task_id,
                current.error
                or ErrorInfo(
                    code="WORKER_INTERRUPTED", message="操作已取消或中断。", retryable=True
                ),
            )
        return True

    def recover(self):
        from sqlalchemy import select

        from app.db.iteration_models import OperationRow
        from app.schemas.iteration import StudyOperation

        with self.repository.engine.connect() as connection:
            rows = connection.scalars(
                select(OperationRow.payload).where(OperationRow.status == "running")
            ).all()
        for payload in rows:
            operation = StudyOperation.model_validate(payload)
            if operation.cancel_requested:
                self.study.acknowledge_cancel(operation.task_id, operation.id)
            else:
                self.study.finish(
                    operation.task_id,
                    operation.id,
                    error=ErrorInfo(
                        code="WORKER_INTERRUPTED",
                        message="操作已中断，请手动重试。",
                        retryable=True,
                    ),
                )
