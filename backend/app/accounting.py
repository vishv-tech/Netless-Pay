"""Trusted internal accounting services; no HTTP routes or external money movement.

Each mutation owns a fresh READ COMMITTED transaction. Results leave this module
only after commit. Verification metadata is supplied by an independently verified,
trusted administrative workflow, which is deliberately not exposed in Sprint 1.
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import build_session_factory
from app.models import AuditEvent, FinancialTransaction, FundingRecord, IdempotencyRecord, LedgerEntry, Participant, RefundRecord, Wallet


class AccountingError(Exception):
    """A rejected operation leaves no money, history, audit, or replay changes."""


class InvalidRequest(AccountingError):
    pass


class InsufficientFunds(AccountingError):
    pass


class WalletDisabled(AccountingError):
    pass


class LimitExceeded(AccountingError):
    pass


class IdempotencyConflict(AccountingError):
    pass


class DuplicateReference(AccountingError):
    pass


class InvalidRefundState(AccountingError):
    pass


class ReconciliationRequired(AccountingError):
    pass


@dataclass(frozen=True)
class OperationResult:
    operation: str
    transaction_id: str | None = None
    wallet_id: str | None = None
    participant_id: str | None = None
    refund_id: str | None = None
    source_wallet_id: str | None = None
    target_wallet_id: str | None = None
    amount_paise: int = 0


@dataclass(frozen=True)
class WalletReconciliation:
    wallet_id: str
    balance_paise: int
    ledger_balance_paise: int
    held_paise: int
    ledger_held_paise: int
    active_refund_holds_paise: int

    @property
    def reconciled(self) -> bool:
        return (self.balance_paise == self.ledger_balance_paise and
                self.held_paise == self.ledger_held_paise == self.active_refund_holds_paise)


@dataclass(frozen=True)
class ReconciliationReport:
    wallets: tuple[WalletReconciliation, ...]
    ledger_pool_paise: int
    verified_net_funding_paise: int
    invalid_transaction_ids: tuple[str, ...]

    @property
    def reconciled(self) -> bool:
        return (all(wallet.reconciled for wallet in self.wallets) and
                self.ledger_pool_paise == self.verified_net_funding_paise and
                not self.invalid_transaction_ids)


def _amount(value: int) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise InvalidRequest("Amount must be positive integer paise within BIGINT range")
    return value


def _text(value: str, name: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise InvalidRequest(f"{name} must be nonblank and at most {limit} characters")
    return value.strip()


def _uuid(value: UUID | str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise InvalidRequest("Invalid identifier") from None


class AccountingService:
    def __init__(self, engine: Engine, settings: Settings):
        if engine.dialect.name != "postgresql":
            raise ValueError("Accounting requires PostgreSQL locking and constraints")
        self.engine = engine
        self.settings = settings
        self.sessions = build_session_factory(engine.execution_options(isolation_level="READ COMMITTED"))

    def _run(self, key: str, operation: str, actor: str, details: dict,
             action: Callable[[Session], OperationResult]) -> OperationResult:
        key = _text(key, "Idempotency key")
        actor = _text(actor, "Actor reference")
        fingerprint = hashlib.sha256(json.dumps(
            {"operation": operation, "actor": actor, **details}, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        lock_id = int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big", signed=True)
        try:
            with self.sessions.begin() as session:
                # Separate two-int namespaces for keys and pool locks; collisions only serialize.
                session.execute(text("SELECT pg_advisory_xact_lock(71001, :key)"), {"key": lock_id})
                previous = session.get(IdempotencyRecord, key)
                if previous is not None:
                    if previous.fingerprint != fingerprint or previous.operation != operation:
                        raise IdempotencyConflict("Key already used with different request details")
                    result = OperationResult(**previous.result)
                else:
                    result = action(session)
                    transaction_id = _uuid(result.transaction_id) if result.transaction_id else None
                    session.add(AuditEvent(kind=operation, actor_reference=actor,
                                           transaction_id=transaction_id, details=asdict(result)))
                    session.add(IdempotencyRecord(key=key, operation=operation, fingerprint=fingerprint,
                                                  transaction_id=transaction_id, result=asdict(result)))
            return result  # The context manager committed, including deferred database checks.
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) == "23505":
                raise DuplicateReference("An external or participant reference is already recorded") from None
            raise

    @staticmethod
    def _pool_lock(session: Session) -> None:
        session.execute(text("SELECT pg_advisory_xact_lock(71002, 0)"))

    @staticmethod
    def _wallets(session: Session, *ids: UUID, require_enabled: bool = True) -> dict[UUID, Wallet]:
        # Every transfer locks BOTH rows in the same immutable primary-key order.
        wallets = {wallet.id: wallet for wallet in session.scalars(
            select(Wallet).where(Wallet.id.in_(ids)).order_by(Wallet.id).with_for_update()
        )}
        if len(wallets) != len(set(ids)):
            raise InvalidRequest("Wallet does not exist")
        totals = {row[0]: (int(row[1]), int(row[2])) for row in session.execute(
            select(LedgerEntry.wallet_id, func.sum(LedgerEntry.balance_delta_paise),
                   func.sum(LedgerEntry.held_delta_paise)).where(LedgerEntry.wallet_id.in_(ids))
            .group_by(LedgerEntry.wallet_id)
        )}
        for wallet in wallets.values():
            if require_enabled and not wallet.enabled:
                raise WalletDisabled("Wallet is disabled")
            if (wallet.balance_paise, wallet.held_paise) != totals.get(wallet.id, (0, 0)):
                raise ReconciliationRequired("Wallet projection differs from its ledger")
        return wallets

    @staticmethod
    def _post(session: Session, kind: str, amount: int, source: UUID | None, target: UUID | None,
              entries: list[tuple[UUID, int, int]]) -> FinancialTransaction:
        transaction = FinancialTransaction(kind=kind, amount_paise=amount,
                                           source_wallet_id=source, target_wallet_id=target)
        session.add(transaction)
        session.flush()
        for wallet_id, balance_delta, held_delta in entries:
            session.add(LedgerEntry(transaction_id=transaction.id, wallet_id=wallet_id,
                                   balance_delta_paise=balance_delta, held_delta_paise=held_delta))
            session.flush()  # DB trigger updates projection; any subsequent error rolls it all back.
        return transaction

    def create_participant_and_wallet(self, *, external_reference: str, display_name: str,
                                      idempotency_key: str, actor_reference: str) -> OperationResult:
        reference = _text(external_reference, "Participant reference")
        name = _text(display_name, "Display name")

        def action(session: Session) -> OperationResult:
            return self.create_identity_in_transaction(session, reference, name)

        return self._run(idempotency_key, "participant_created", actor_reference,
                         {"external_reference": reference, "display_name": name}, action)

    @staticmethod
    def create_identity_in_transaction(session: Session, reference: str, name: str) -> OperationResult:
        """Shared by accounting and admin enrollment; caller owns the transaction/audit."""
        participant = Participant(external_reference=_text(reference, "Participant reference"),
                                  display_name=_text(name, "Display name"))
        session.add(participant)
        session.flush()
        wallet = Wallet(participant_id=participant.id)
        session.add(wallet)
        session.flush()
        return OperationResult("participant_created", participant_id=str(participant.id), wallet_id=str(wallet.id))

    def credit_verified_funding(self, *, wallet_id: UUID | str, amount_paise: int,
                                external_reference: str, verification_reference: str, verified_by: str,
                                idempotency_key: str) -> OperationResult:
        wallet_id, amount = _uuid(wallet_id), _amount(amount_paise)
        external = _text(external_reference, "Verified deposit reference")
        verification = _text(verification_reference, "Authoritative verification reference", 256)

        def action(session: Session) -> OperationResult:
            self._pool_lock(session)
            wallet = self._wallets(session, wallet_id)[wallet_id]
            if session.scalar(select(FundingRecord.id).where(FundingRecord.external_reference == external)):
                raise DuplicateReference("Deposit reference already credited")
            if wallet.balance_paise + amount > self.settings.max_wallet_balance_paise:
                raise LimitExceeded("Maximum wallet balance exceeded")
            reserve = int(session.scalar(select(func.coalesce(func.sum(LedgerEntry.balance_delta_paise), 0))))
            if reserve + amount > self.settings.max_pool_reserve_paise:
                raise LimitExceeded("Maximum recorded pool reserve exceeded")
            transaction = self._post(session, "funding", amount, None, wallet_id, [(wallet_id, amount, 0)])
            session.add(FundingRecord(wallet_id=wallet_id, transaction_id=transaction.id, amount_paise=amount,
                                     external_reference=external, verification_reference=verification,
                                     verified_by=_text(verified_by, "Verifier")))
            return OperationResult("funding", transaction_id=str(transaction.id), wallet_id=str(wallet_id), amount_paise=amount)

        return self._run(idempotency_key, "funding", verified_by,
                         {"wallet_id": str(wallet_id), "amount_paise": amount,
                          "external_reference": external, "verification_reference": verification}, action)

    def transfer(self, *, source_wallet_id: UUID | str, target_wallet_id: UUID | str,
                 amount_paise: int, idempotency_key: str, actor_reference: str) -> OperationResult:
        source, target, amount = _uuid(source_wallet_id), _uuid(target_wallet_id), _amount(amount_paise)
        if source == target:
            raise InvalidRequest("Self-transfers are not allowed")

        def action(session: Session) -> OperationResult:
            if amount > self.settings.max_payment_paise:
                raise LimitExceeded("Maximum individual payment exceeded")
            wallets = self._wallets(session, source, target)
            if wallets[source].balance_paise - wallets[source].held_paise < amount:
                raise InsufficientFunds("Insufficient spendable balance")
            if wallets[target].balance_paise + amount > self.settings.max_wallet_balance_paise:
                raise LimitExceeded("Maximum recipient wallet balance exceeded")
            transaction = self._post(session, "transfer", amount, source, target,
                                     [(source, -amount, 0), (target, amount, 0)])
            return OperationResult("transfer", transaction_id=str(transaction.id), source_wallet_id=str(source),
                                   target_wallet_id=str(target), amount_paise=amount)

        return self._run(idempotency_key, "transfer", actor_reference,
                         {"source_wallet_id": str(source), "target_wallet_id": str(target), "amount_paise": amount}, action)

    def create_refund_hold(self, *, wallet_id: UUID | str, amount_paise: int, reason: str,
                           idempotency_key: str, actor_reference: str) -> OperationResult:
        wallet_id, amount = _uuid(wallet_id), _amount(amount_paise)
        reason = _text(reason, "Refund reason", 256)

        def action(session: Session) -> OperationResult:
            wallet = self._wallets(session, wallet_id)[wallet_id]
            if wallet.balance_paise - wallet.held_paise < amount:
                raise InsufficientFunds("Insufficient spendable balance for refund hold")
            transaction = self._post(session, "refund_hold", amount, wallet_id, None, [(wallet_id, 0, amount)])
            refund = RefundRecord(id=uuid4(), wallet_id=wallet_id, amount_paise=amount,
                                  reason=reason, hold_transaction_id=transaction.id)
            session.add(refund)
            return OperationResult("refund_hold", transaction_id=str(transaction.id), wallet_id=str(wallet_id),
                                   refund_id=str(refund.id), amount_paise=amount)

        return self._run(idempotency_key, "refund_hold", actor_reference,
                         {"wallet_id": str(wallet_id), "amount_paise": amount, "reason": reason}, action)

    def release_refund_hold(self, *, refund_id: UUID | str, idempotency_key: str,
                            actor_reference: str) -> OperationResult:
        return self._finish_refund(_uuid(refund_id), idempotency_key, actor_reference, None, None)

    def record_completed_refund(self, *, refund_id: UUID | str, external_reference: str,
                                verification_reference: str, verified_by: str, idempotency_key: str) -> OperationResult:
        return self._finish_refund(_uuid(refund_id), idempotency_key, verified_by,
                                   _text(external_reference, "Completed refund reference"),
                                   _text(verification_reference, "Authoritative verification reference", 256))

    def _finish_refund(self, refund_id: UUID, key: str, actor: str, external: str | None,
                       verification: str | None) -> OperationResult:
        operation = "refund_complete" if external is not None else "refund_release"

        def action(session: Session) -> OperationResult:
            if external is not None:
                self._pool_lock(session)
            refund = session.scalar(select(RefundRecord).where(RefundRecord.id == refund_id).with_for_update())
            if refund is None:
                raise InvalidRequest("Refund does not exist")
            if refund.status != "held":
                raise InvalidRefundState("Refund is already released or completed")
            # Existing obligations can be released/completed even if a wallet is disabled.
            self._wallets(session, refund.wallet_id, require_enabled=False)
            if external is not None and session.scalar(
                select(RefundRecord.id).where(RefundRecord.external_reference == external)
            ):
                raise DuplicateReference("Completed refund reference already recorded")
            transaction = self._post(session, operation, refund.amount_paise, refund.wallet_id, None,
                                     [(refund.wallet_id, -refund.amount_paise if external else 0, -refund.amount_paise)])
            if external is None:
                refund.status, refund.release_transaction_id = "released", transaction.id
            else:
                refund.status, refund.completion_transaction_id = "completed", transaction.id
                refund.external_reference, refund.verification_reference = external, verification
                refund.verified_by, refund.completed_at = _text(actor, "Verifier"), datetime.now(timezone.utc)
            return OperationResult(operation, transaction_id=str(transaction.id), wallet_id=str(refund.wallet_id),
                                   refund_id=str(refund.id), amount_paise=refund.amount_paise)

        return self._run(key, operation, actor,
                         {"refund_id": str(refund_id), "external_reference": external,
                          "verification_reference": verification}, action)

    def reconcile(self) -> ReconciliationReport:
        """Read one consistent snapshot; report discrepancies without rewriting history."""
        with self.sessions.begin() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            totals = {row[0]: (int(row[1]), int(row[2])) for row in session.execute(
                select(LedgerEntry.wallet_id, func.sum(LedgerEntry.balance_delta_paise),
                       func.sum(LedgerEntry.held_delta_paise)).group_by(LedgerEntry.wallet_id)
            )}
            holds = {row[0]: int(row[1]) for row in session.execute(
                select(RefundRecord.wallet_id, func.sum(RefundRecord.amount_paise))
                .where(RefundRecord.status == "held").group_by(RefundRecord.wallet_id)
            )}
            wallets = tuple(WalletReconciliation(str(wallet.id), wallet.balance_paise,
                            totals.get(wallet.id, (0, 0))[0], wallet.held_paise,
                            totals.get(wallet.id, (0, 0))[1], holds.get(wallet.id, 0))
                            for wallet in session.scalars(select(Wallet).order_by(Wallet.id)))
            funding = int(session.scalar(select(func.coalesce(func.sum(FundingRecord.amount_paise), 0))))
            refunded = int(session.scalar(select(func.coalesce(func.sum(RefundRecord.amount_paise), 0))
                                         .where(RefundRecord.status == "completed")))
            entries: dict[UUID, set] = defaultdict(set)
            for entry in session.scalars(select(LedgerEntry)):
                entries[entry.transaction_id].add((entry.wallet_id, entry.balance_delta_paise, entry.held_delta_paise))
            invalid = []
            for txn in session.scalars(select(FinancialTransaction).order_by(FinancialTransaction.id)):
                expected = {
                    "transfer": {(txn.source_wallet_id, -txn.amount_paise, 0), (txn.target_wallet_id, txn.amount_paise, 0)},
                    "funding": {(txn.target_wallet_id, txn.amount_paise, 0)},
                    "refund_hold": {(txn.source_wallet_id, 0, txn.amount_paise)},
                    "refund_release": {(txn.source_wallet_id, 0, -txn.amount_paise)},
                    "refund_complete": {(txn.source_wallet_id, -txn.amount_paise, -txn.amount_paise)},
                }[txn.kind]
                if entries[txn.id] != expected:
                    invalid.append(str(txn.id))
            return ReconciliationReport(wallets, sum(value[0] for value in totals.values()),
                                        funding - refunded, tuple(invalid))
