from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app


def test_liveness_does_not_touch_database(settings: Settings) -> None:
    engine = MagicMock(spec=Engine)
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    engine.connect.assert_not_called()


def test_readiness_queries_database(settings: Settings) -> None:
    engine = MagicMock(spec=Engine)
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}
    connection = engine.connect.return_value.__enter__.return_value
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"
    engine.connect.return_value.__exit__.assert_called_once()


def test_unavailable_database_is_safe_and_liveness_survives(settings: Settings) -> None:
    engine = MagicMock(spec=Engine)
    engine.connect.side_effect = OperationalError("private connection details", {}, Exception("secret"))
    with TestClient(create_app(settings, engine)) as client:
        response = client.get("/health/ready")
        assert client.get("/health").status_code == 200
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert "secret" not in response.text


def test_query_failure_is_not_ready(settings: Settings) -> None:
    engine = MagicMock(spec=Engine)
    engine.connect.return_value.__enter__.return_value.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("timeout")
    )
    with TestClient(create_app(settings, engine)) as client:
        assert client.get("/health/ready").status_code == 503


def test_no_public_accounting_endpoints(settings: Settings) -> None:
    with TestClient(create_app(settings, MagicMock(spec=Engine))) as client:
        paths = set(client.get("/openapi.json").json()["paths"])
        assert {"/health", "/health/ready", "/api/v1/auth/login"} <= paths
        assert not any(word in path for path in paths for word in ("/transfer", "/funding", "/refund", "/sms", "/upi", "/qr"))
