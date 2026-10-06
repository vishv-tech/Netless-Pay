"""Run with migration credentials, never in the runtime backend process."""
from alembic import command
from alembic.config import Config

from app.config import Settings
from app.database import build_engine
from app.db_roles import grant_runtime


def main():
    engine = build_engine(Settings())
    try:
        with engine.begin() as connection:
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            grant_runtime(connection)
    finally:
        engine.dispose()
    print("Migration and runtime grants complete.")


if __name__ == "__main__":
    main()
