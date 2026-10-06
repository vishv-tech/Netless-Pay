"""Accounting storage. All monetary columns are signed integer paise (BIGINT)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Participant(Identity, Base):
    __tablename__ = "participants"
    external_reference: Mapped[str] = mapped_column(String(128), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))


class Wallet(Identity, Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("balance_paise >= 0", name="wallet_balance_nonnegative"),
        CheckConstraint("held_paise >= 0 AND held_paise <= balance_paise", name="wallet_hold_bounds"),
    )
    participant_id: Mapped[UUID] = mapped_column(ForeignKey("participants.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Projection maintained by the ledger INSERT trigger, not by service UPDATEs.
    balance_paise: Mapped[int] = mapped_column(BigInteger, server_default="0")
    held_paise: Mapped[int] = mapped_column(BigInteger, server_default="0")


class FinancialTransaction(Identity, Base):
    __tablename__ = "financial_transactions"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="transaction_amount_positive"),
        CheckConstraint(
            "(kind = 'funding' AND source_wallet_id IS NULL AND target_wallet_id IS NOT NULL) OR "
            "(kind = 'transfer' AND source_wallet_id IS NOT NULL AND target_wallet_id IS NOT NULL "
            "AND source_wallet_id <> target_wallet_id) OR "
            "(kind IN ('refund_hold', 'refund_release', 'refund_complete') "
            "AND source_wallet_id IS NOT NULL AND target_wallet_id IS NULL)",
            name="transaction_shape",
        ),
    )
    kind: Mapped[str] = mapped_column(String(32))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    source_wallet_id: Mapped[UUID | None] = mapped_column(ForeignKey("wallets.id"), index=True)
    target_wallet_id: Mapped[UUID | None] = mapped_column(ForeignKey("wallets.id"), index=True)


class LedgerEntry(Identity, Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        UniqueConstraint("transaction_id", "wallet_id", name="ledger_transaction_wallet_unique"),
        CheckConstraint("balance_delta_paise <> 0 OR held_delta_paise <> 0", name="ledger_nonzero"),
        Index("ix_ledger_wallet_created", "wallet_id", "created_at"),
    )
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transactions.id"))
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"))
    balance_delta_paise: Mapped[int] = mapped_column(BigInteger)
    held_delta_paise: Mapped[int] = mapped_column(BigInteger, server_default="0")


class FundingRecord(Identity, Base):
    __tablename__ = "funding_records"
    __table_args__ = (CheckConstraint("amount_paise > 0", name="funding_amount_positive"),)
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transactions.id"), unique=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    external_reference: Mapped[str] = mapped_column(String(128), unique=True)
    verification_reference: Mapped[str] = mapped_column(String(256))
    verified_by: Mapped[str] = mapped_column(String(128))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefundRecord(Identity, Base):
    __tablename__ = "refund_records"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="refund_amount_positive"),
        CheckConstraint(
            "(status = 'held' AND release_transaction_id IS NULL AND completion_transaction_id IS NULL "
            "AND external_reference IS NULL AND verification_reference IS NULL AND verified_by IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'released' AND release_transaction_id IS NOT NULL AND completion_transaction_id IS NULL "
            "AND external_reference IS NULL AND verification_reference IS NULL AND verified_by IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND release_transaction_id IS NULL AND completion_transaction_id IS NOT NULL "
            "AND external_reference IS NOT NULL AND verification_reference IS NOT NULL AND verified_by IS NOT NULL "
            "AND completed_at IS NOT NULL)", name="refund_state_shape",
        ),
    )
    wallet_id: Mapped[UUID] = mapped_column(ForeignKey("wallets.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16), server_default="held")
    reason: Mapped[str] = mapped_column(String(256))
    hold_transaction_id: Mapped[UUID] = mapped_column(ForeignKey("financial_transactions.id"), unique=True)
    release_transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transactions.id"), unique=True)
    completion_transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transactions.id"), unique=True)
    external_reference: Mapped[str | None] = mapped_column(String(128), unique=True)
    verification_reference: Mapped[str | None] = mapped_column(String(256))
    verified_by: Mapped[str | None] = mapped_column(String(128))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    kind: Mapped[str] = mapped_column(String(32))
    actor_reference: Mapped[str] = mapped_column(String(128))
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transactions.id"), index=True)
    details: Mapped[dict] = mapped_column(JSONB)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSONB)
    transaction_id: Mapped[UUID | None] = mapped_column(ForeignKey("financial_transactions.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
