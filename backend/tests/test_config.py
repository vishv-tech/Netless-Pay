import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_limits_and_secret_redaction(settings: Settings) -> None:
    assert settings.max_wallet_balance_paise == 10000
    assert settings.max_payment_paise == 2000
    assert settings.max_pool_reserve_paise == 50000
    assert settings.db_password.get_secret_value() not in repr(settings)
    assert settings.db_password.get_secret_value() not in str(settings.database_url)


def test_environment_override(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PAYMENT_PAISE", "1500")
    override = Settings(_env_file=None, db_password=settings.db_password)
    assert override.max_payment_paise == 1500


@pytest.mark.parametrize("invalid", [0, -1, 20.5, 2000.0, True, "20.5", "2000.0", "2e3"])
def test_rejects_invalid_paise(settings: Settings, invalid: object) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_password=settings.db_password, max_payment_paise=invalid)


def test_rejects_inconsistent_limits(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_password=settings.db_password, max_payment_paise=10001)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_password=settings.db_password, max_pool_reserve_paise=9999)


@pytest.mark.parametrize("password", ["", "   "])
def test_rejects_empty_password(settings: Settings, password: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, db_password=password)


def test_requires_password(settings: Settings) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
