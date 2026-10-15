from sqlalchemy import URL

from alembic import context
from app.core.config import Settings
from app.db import context_models, event_models, iteration_models, models, review_models  # noqa: F401 -- register all versioned metadata
from app.db.session import Base, create_database_engine

config = context.config
target_metadata = Base.metadata


def configure_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=URL.create("sqlite", database=str(Settings().data_dir / "app.db")),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    configure_connection(config.attributes["connection"])
else:
    engine = create_database_engine(Settings().data_dir / "app.db")
    try:
        with engine.connect() as connection:
            configure_connection(connection)
    finally:
        engine.dispose()
