import argparse
import asyncio
from uuid import UUID

from app.core.config import Settings
from app.core.locking import native_lock
from app.db.repository import TaskRepository, initialize_database
from app.db.study_repository import StudyRepository
from app.services.operations import run_operation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", type=UUID, required=True)
    parser.add_argument("--operation-id", type=UUID, required=True)
    args = parser.parse_args()
    settings = Settings()
    with native_lock(settings.data_dir / "tasks" / str(args.task_id) / ".attempt.lock"):
        engine = initialize_database(settings.data_dir / "app.db")
        try:
            operation = StudyRepository(engine).operation(args.task_id, args.operation_id)
            if operation.status != "running":
                return 2
            asyncio.run(run_operation(operation, settings, TaskRepository(engine)))
        finally:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
