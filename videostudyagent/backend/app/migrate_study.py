"""Explicit local migration with a SQLite backup; never invoked by server startup."""

import argparse
import sqlite3
from datetime import datetime

from sqlalchemy import select

from app.core.config import Settings
from app.core.locking import native_lock
from app.db.iteration_models import OperationRow
from app.db.models import TaskRow
from app.db.repository import initialize_database
from app.db.study_repository import StudyRepository
from app.services.study_versions import LegacyStudyImporter


def migrate(settings, target="0003_study_foundation"):
    path = settings.data_dir / "app.db"
    with native_lock(settings.data_dir / ".worker.lock").acquire(timeout=0):
        if path.exists():
            backup = (
                settings.data_dir / "backups" / f"before-schema-{datetime.now():%Y%m%d%H%M%S%f}.db"
            )
            backup.parent.mkdir(parents=True, exist_ok=True)
            with (
                sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as source,
                sqlite3.connect(backup) as backup_connection,
            ):
                source.backup(backup_connection)
        engine = initialize_database(path, revision=target)
        try:
            with engine.connect() as connection:
                tasks = connection.scalars(select(TaskRow.id)).all()
            importer = LegacyStudyImporter(settings.data_dir, StudyRepository(engine))
            for task_id in tasks:
                with engine.connect() as connection:
                    native = connection.scalar(
                        select(OperationRow.id)
                        .where(
                            OperationRow.task_id == task_id,
                            OperationRow.idempotency_key.like("initial:%"),
                        )
                        .limit(1)
                    )
                if native is None:
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
    parser.add_argument(
        "--target",
        choices=[
            "0003_study_foundation",
            "0004_video_context",
            "0005_quality_reviews",
            "0006_evidence_index",
            "0007_operation_events",
        ],
        default="0003_study_foundation",
    )
    args = parser.parse_args()
    print(
        f"Migration complete: {migrate(Settings(), args.target)} courses indexed; no model calls."
    )


if __name__ == "__main__":
    main()
