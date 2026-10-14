import argparse
import asyncio
from uuid import UUID

from filelock import Timeout

from app.agent.loop import StudyAgent
from app.agent.tools import StudyTools
from app.core.config import Settings
from app.core.errors import StudyError
from app.core.locking import native_lock
from app.db.repository import TaskRepository, initialize_database
from app.providers.budget import BoundedLLM
from app.providers.deepseek import DeepSeekClient
from app.schemas.common import ErrorInfo


async def execute_study(task, settings, repository, llm=None, asr=None):
    if not task.options.generate_notes and not task.options.generate_quiz:
        from app.schemas.providers import ToolCall

        tools = StudyTools(task, settings, repository, None, asr)
        if tools.state()["has_subtitle"]:
            await tools.execute(ToolCall(id="prepare", name="load_subtitles", arguments={}), 1)
        else:
            receipt = await tools.execute(
                ToolCall(id="audio", name="extract_audio", arguments={}), 1
            )
            await tools.execute(
                ToolCall(
                    id="asr",
                    name="transcribe_audio",
                    arguments={"audio_artifact_id": str(receipt["artifact_id"])},
                ),
                2,
            )
        return tools
    client = llm or DeepSeekClient(settings)
    bounded = client if isinstance(client, BoundedLLM) else BoundedLLM(client, settings)
    tools = StudyTools(task, settings, repository, bounded, asr)
    await StudyAgent(tools, bounded, settings).run()
    if not tools.complete():
        raise StudyError("AGENT_INCOMPLETE", "最终产物校验未通过。", 422, True)
    return tools


async def run_task(task, settings, repository, llm=None, asr=None):
    try:
        await execute_study(task, settings, repository, llm, asr)
        repository.finish(task.id)
    except StudyError as exc:
        repository.finish(
            task.id,
            ErrorInfo(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable or exc.code == "LLM_CONFIGURATION_ERROR",
                step=exc.step,
            ),
        )
    except Exception:
        repository.finish(
            task.id, ErrorInfo(code="INTERNAL_ERROR", message="任务执行未完成。", retryable=True)
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", type=UUID, required=True)
    args = parser.parse_args()
    settings = Settings()
    lock = native_lock(settings.data_dir / "tasks" / str(args.task_id) / ".attempt.lock")
    try:
        with lock.acquire(timeout=0):
            repository = TaskRepository(initialize_database(settings.data_dir / "app.db"))
            try:
                task = repository.get(args.task_id)
                if task.status != "running":
                    return 2
                asyncio.run(run_task(task, settings, repository))
            finally:
                repository.engine.dispose()
    except (Timeout, StudyError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
