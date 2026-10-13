"""Browser-test fixture only; production never installs a scripted LLM."""

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from uuid import uuid4

from app.core.config import PROJECT_ROOT, Settings
from app.core.locking import native_lock
from app.db.repository import TaskRepository, initialize_database
from app.main import create_app
from app.task_runner import run_task
from app.worker import Worker
from tests.scripted_llm import ScriptedStudyModel

if os.environ.get("VSA_E2E") != "1":
    raise RuntimeError("Test fixture requires explicit VSA_E2E=1")

settings = Settings(
    _env_file=None, environment="test", data_dir=PROJECT_ROOT / ".cache" / f"e2e-{uuid4()}"
)
app = create_app(settings)
original_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(application):
    stop = threading.Event()
    repo = TaskRepository(initialize_database(settings.data_dir / "app.db"))

    def process():
        with native_lock(settings.data_dir / ".worker.lock"):
            repo.recover_interrupted()
            worker = Worker(
                settings,
                repo,
                lambda task: asyncio.run(run_task(task, settings, repo, ScriptedStudyModel())),
            )
            while not stop.is_set():
                if not worker.run_once():
                    stop.wait(0.1)

    thread = threading.Thread(target=process, daemon=True)
    thread.start()
    try:
        async with original_lifespan(application):
            yield
    finally:
        stop.set()
        thread.join(timeout=15)
        repo.engine.dispose()


app.router.lifespan_context = lifespan
