"""Environment configuration. Money is represented only in integer paise."""

import re
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "offlinewallet"
    db_user: str = "wallet_runtime"
    db_password: SecretStr
    max_wallet_balance_paise: int = Field(default=10000, gt=0)
    max_payment_paise: int = Field(default=2000, gt=0)
    max_pool_reserve_paise: int = Field(default=50000, gt=0)
    device_master_key: SecretStr | None = None
    enrollment_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    gateway_session_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    auth_rate_window_seconds: int = Field(default=900, ge=1, le=3600)
    login_attempt_limit: int = Field(default=5, ge=1, le=100)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    redemption_attempt_limit: int = Field(default=5, ge=1, le=100)
    redemption_ip_limit: int = Field(default=20, ge=1, le=1000)

    @field_validator("db_host", "db_name", "db_user")
    @classmethod
    def nonempty_database_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Database configuration must not be blank")
        return value

    @field_validator("db_password")
    @classmethod
    def nonempty_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Set DB_PASSWORD to a unique local password")
        return value

    @field_validator(
        "max_wallet_balance_paise", "max_payment_paise", "max_pool_reserve_paise",
        mode="before",
    )
    @classmethod
    def integer_paise_only(cls, value: object) -> int:
        if type(value) is int:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            return int(value)
        raise ValueError("Limits must be whole integer paise")

    @model_validator(mode="after")
    def ordered_limits(self) -> "Settings":
        if not self.max_payment_paise <= self.max_wallet_balance_paise <= self.max_pool_reserve_paise:
            raise ValueError("Limits must satisfy payment <= wallet balance <= pool reserve")
        return self

    @property
    def database_url(self) -> URL:
        # URL.create safely handles punctuation in passwords, without string interpolation.
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
