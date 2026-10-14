"""Explicit local migration with a SQLite backup; never invoked by server startup."""

import argparse
import sqlite3
from datetime import datetime

from sqlalchemy import select

from app.core.config import Settings
from app.core.locking import native_lock
from app.db.models import TaskRow
from app.db.repository import initialize_database
from app.db.study_repository import StudyRepository
from app.services.study_versions import LegacyStudyImporter


def migrate(settings):
    path = settings.data_dir / "app.db"
    with native_lock(settings.data_dir / ".worker.lock").acquire(timeout=0):
        if path.exists():
            backup = settings.data_dir / "backups" / f"before-v2-{datetime.now():%Y%m%d%H%M%S%f}.db"
            backup.parent.mkdir(parents=True, exist_ok=True)
            with (
                sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source,
                sqlite3.connect(backup) as target,
            ):
                source.backup(target)
        engine = initialize_database(path, revision="0003_study_foundation")
        try:
            with engine.connect() as connection:
                tasks = connection.scalars(select(TaskRow.id)).all()
            importer = LegacyStudyImporter(settings.data_dir, StudyRepository(engine))
            for task_id in tasks:
                importer.import_task(task_id)
        finally:
            engine.dispose()
    return len(tasks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-stopped",
        action="store_true",
        required=True,
        help="Confirm that the API and old Worker have both been stopped",
    )
    parser.parse_args()
    print(f"Migration complete: {migrate(Settings())} courses indexed; no model calls.")


if __name__ == "__main__":
    main()
