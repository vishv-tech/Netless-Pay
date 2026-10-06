from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator, model_validator

from app.security import normalize_phone


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Login(Input):
    phone: str = Field(min_length=1, max_length=32)
    password: SecretStr = Field(min_length=1, max_length=128)
    device_id: UUID | None = None
    device_secret: SecretStr | None = Field(default=None, min_length=40, max_length=128)

    @model_validator(mode="after")
    def device_pair(self):
        if (self.device_id is None) != (self.device_secret is None):
            raise ValueError("Device ID and secret must be supplied together")
        return self


class AdminLogin(Input):
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class Enroll(Input):
    name: str = Field(min_length=1, max_length=128)
    phone: str = Field(min_length=1, max_length=32)
    admin_confirmed_phone: StrictBool

    @field_validator("phone")
    @classmethod
    def phone_number(cls, value):
        return normalize_phone(value)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()

    @field_validator("admin_confirmed_phone")
    @classmethod
    def confirmed(cls, value):
        if not value:
            raise ValueError("Administrator must manually confirm phone ownership")
        return value


class Redeem(Input):
    enrollment_token: SecretStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class PasswordChange(Input):
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=1, max_length=128)


class StatusChange(Input):
    status: Literal["suspended", "active"]


class RegisterDevice(Input):
    label: str = Field(min_length=1, max_length=80)

    @field_validator("label")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Device label cannot be blank")
        return value.strip()


class SessionView(BaseModel):
    participant_id: UUID | None = None
    session_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: datetime
    role: Literal["PARTICIPANT", "ADMIN", "GATEWAY"]


class EnrollmentView(BaseModel):
    participant_id: UUID
    account_id: UUID
    enrollment_token: str
    expires_at: datetime
    phone_confirmation: Literal["admin-confirmed phone"] = "admin-confirmed phone"


class ProfileView(BaseModel):
    participant_id: UUID
    name: str
    phone: str
    phone_confirmation: str
    status: str


class WalletView(BaseModel):
    wallet_id: UUID
    balance_paise: int
    held_paise: int
    available_paise: int
    enabled: bool
    source: Literal["confirmed-ledger"] = "confirmed-ledger"


class TransactionView(BaseModel):
    transaction_id: UUID
    kind: str
    amount_paise: int
    balance_delta_paise: int
    held_delta_paise: int
    created_at: datetime


class DeviceView(BaseModel):
    device_id: UUID
    participant_id: UUID
    label: str
    status: Literal["pending", "active", "revoked"]
    registered_at: datetime
    revoked_at: datetime | None
    last_seen_at: datetime | None
    approved_at: datetime | None
    secret_version: int


class DeviceEnrollmentView(DeviceView):
    device_secret: str


class AuditView(BaseModel):
    id: UUID
    kind: str
    actor_reference: str
    created_at: datetime
    details: dict


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int
