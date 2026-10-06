"""Authentication records are separate from participant accounting identity."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import Identity


class Account(Identity, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('PARTICIPANT', 'ADMIN', 'GATEWAY')", name="account_role"),
        CheckConstraint("status IN ('pending', 'active', 'suspended')", name="account_status"),
        CheckConstraint("status <> 'active' OR role = 'GATEWAY' OR password_hash IS NOT NULL", name="active_password"),
        CheckConstraint("phone IS NULL OR phone ~ '^\\+91[6-9][0-9]{9}$'", name="indian_phone"),
        CheckConstraint("(role = 'PARTICIPANT' AND participant_id IS NOT NULL AND phone IS NOT NULL "
                        "AND phone_confirmation = 'admin-confirmed phone' AND phone_confirmed_by IS NOT NULL "
                        "AND phone_confirmed_at IS NOT NULL) OR (role <> 'PARTICIPANT' AND participant_id IS NULL "
                        "AND phone IS NULL)", name="account_identity"),
    )
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    login_name: Mapped[str] = mapped_column(String(128), unique=True)
    participant_id: Mapped[UUID | None] = mapped_column(ForeignKey("participants.id"), unique=True)
    phone: Mapped[str | None] = mapped_column(String(13), unique=True)
    phone_confirmation: Mapped[str | None] = mapped_column(String(32))
    phone_confirmed_by: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    phone_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(512))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentToken(Identity, Base):
    __tablename__ = "enrollment_tokens"
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Device(Identity, Base):
    __tablename__ = "devices"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'active', 'revoked')", name="device_status"),
        CheckConstraint("secret_version > 0", name="device_secret_version"),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="device_revocation"),
        CheckConstraint("status <> 'active' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)", name="device_approval"),
        Index("one_active_device", "participant_id", unique=True, postgresql_where=text("status = 'active'")),
    )
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("participants.id"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16))
    secret_version: Mapped[int] = mapped_column(Integer)
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Identity, Base):
    __tablename__ = "auth_sessions"
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("devices.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthRateBucket(Base):
    __tablename__ = "auth_rate_buckets"
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
