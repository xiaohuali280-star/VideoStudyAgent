from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.db.iteration_models import ITERATION_TABLES
from app.db.session import create_database_engine


def test_baseline_migration_is_repeatable_and_persistent(tmp_path):
    database_path = tmp_path / "isolated" / "test.db"
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001_baseline")
            command.upgrade(config, "0001_baseline")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    finally:
        engine.dispose()

    reopened = create_database_engine(database_path)
    try:
        with reopened.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                == "0001_baseline"
            )
        with reopened.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            assert set(inspect(connection).get_table_names()) == set(ITERATION_TABLES) | {
                "alembic_version",
                "tasks",
                "assets",
                "task_steps",
                "artifacts",
                "cache_entries",
                "video_context_snapshots",
                "quality_reviews",
                "review_repairs",
                "operation_events",
                "event_retention",
                "evidence_index_manifests",
                "evidence_documents",
                "evidence_fts",
                "evidence_fts_data",
                "evidence_fts_idx",
                "evidence_fts_content",
                "evidence_fts_docsize",
                "evidence_fts_config",
            }
            command.downgrade(config, "0001_baseline")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            command.downgrade(config, "base")
            assert connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() == 0
    finally:
        reopened.dispose()
