import os
import base64
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, text

from app.config import Settings


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # No .env loading and no inherited demonstration configuration.
    for name in tuple(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)
    return Settings(_env_file=None, db_password="test-only-not-a-real-secret",
                    device_master_key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())


@pytest.fixture(scope="session")
def postgres_admin_engine():
    if os.environ.get("LEDGER_TEST_ISOLATED") != "1":
        pytest.skip("Run python backend/scripts/check_compose.py for isolated PostgreSQL tests")
    # Explicit opt-in + a fixed test database; never fall back to DB_* or .env.
    if os.environ.get("LEDGER_TEST_DB_NAME") != "offlinewallet_test":
        pytest.fail("Refusing to run accounting tests outside offlinewallet_test")
    engine = create_engine(URL.create(
        "postgresql+psycopg", host=os.environ["LEDGER_TEST_DB_HOST"],
        username=os.environ["LEDGER_TEST_DB_USER"], password=os.environ["LEDGER_TEST_DB_PASSWORD"],
        database="offlinewallet_test",
    ), hide_parameters=True, connect_args={"connect_timeout": 3})
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT current_database()")) == "offlinewallet_test"
    yield engine
    engine.dispose()


def migration_config(connection):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@pytest.fixture
def accounting_engine(postgres_admin_engine):
    schema = "ledger_test_" + uuid4().hex
    with postgres_admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(postgres_admin_engine.url, hide_parameters=True, pool_size=8,
                           connect_args={"options": f"-c search_path={schema} -c statement_timeout=15000"})
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")
        yield engine
    finally:
        engine.dispose()
        # Only the generated schema in the explicitly isolated database is removed.
        with postgres_admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
