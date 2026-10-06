"""Real PostgreSQL tests: independent transactions, triggers and locks, not SQLite."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from uuid import UUID, uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounting import AccountingService, DuplicateReference, IdempotencyConflict, InsufficientFunds, InvalidRefundState, InvalidRequest, LimitExceeded, ReconciliationRequired, WalletDisabled
from app.database import Base
from app.models import AuditEvent, FinancialTransaction, FundingRecord, IdempotencyRecord, LedgerEntry, Participant, RefundRecord, Wallet
from conftest import migration_config

pytestmark = pytest.mark.postgres


@pytest.fixture
def service(accounting_engine, settings):
    return AccountingService(accounting_engine, settings)


def participant(service, reference=None):
    reference = reference or uuid4().hex
    return service.create_participant_and_wallet(external_reference=reference, display_name="Test participant",
                                                idempotency_key=uuid4().hex, actor_reference="test-admin")


def fund(service, wallet, amount, key=None, reference=None):
    return service.credit_verified_funding(wallet_id=wallet, amount_paise=amount,
        external_reference=reference or uuid4().hex, verification_reference="synthetic-bank-record",
        verified_by="test-verifier", idempotency_key=key or uuid4().hex)


def transfer(service, source, target, amount=1000, key=None):
    return service.transfer(source_wallet_id=source, target_wallet_id=target, amount_paise=amount,
                            idempotency_key=key or uuid4().hex, actor_reference="test-participant")


def balance(service, wallet):
    with service.sessions() as session:
        row = session.get(Wallet, UUID(wallet))
        return row.balance_paise, row.held_paise


def counts(service):
    with service.sessions() as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in
                     (FinancialTransaction, LedgerEntry, FundingRecord, RefundRecord, AuditEvent, IdempotencyRecord))


def test_create_empty_wallet_and_replay(service):
    args = dict(external_reference="participant-1", display_name="Test", idempotency_key="create-1", actor_reference="admin")
    first = service.create_participant_and_wallet(**args)
    assert service.create_participant_and_wallet(**args) == first
    assert balance(service, first.wallet_id) == (0, 0)
    assert counts(service) == (0, 0, 0, 0, 1, 1)
    assert service.reconcile().reconciled


def test_successful_transfer_is_balanced(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 3000)
    result = transfer(service, source, target, 1500)
    assert balance(service, source) == (1500, 0)
    assert balance(service, target) == (1500, 0)
    with service.sessions() as session:
        entries = session.scalars(select(LedgerEntry).where(LedgerEntry.transaction_id == UUID(result.transaction_id))).all()
        assert len(entries) == 2
        assert sorted(entry.balance_delta_paise for entry in entries) == [-1500, 1500]
        assert sum(entry.held_delta_paise for entry in entries) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.transaction_id == UUID(result.transaction_id))) == 1
    assert service.reconcile().reconciled


def test_insufficient_funds_is_noop(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 999)
    before = counts(service)
    with pytest.raises(InsufficientFunds):
        transfer(service, source, target)
    assert counts(service) == before
    assert balance(service, source) == (999, 0)
    assert balance(service, target) == (0, 0)


def test_self_transfer_rejected(service):
    wallet = participant(service).wallet_id
    with pytest.raises(InvalidRequest, match="Self"):
        transfer(service, wallet, wallet)


@pytest.mark.parametrize("amount", [0, -1, 1.5, 1000.0, True, "1000", 2**63])
def test_invalid_amounts_rejected(service, amount):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    with pytest.raises(InvalidRequest):
        transfer(service, source, target, amount)


def test_payment_limit_and_recipient_balance_limit(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 5000)
    fund(service, target, 9500)
    with pytest.raises(LimitExceeded, match="payment"):
        transfer(service, source, target, 2001)
    with pytest.raises(LimitExceeded, match="recipient"):
        transfer(service, source, target, 501)
    assert balance(service, source) == (5000, 0)


@pytest.mark.parametrize("disabled_side", ["source", "target"])
def test_disabled_wallets_rejected(service, disabled_side):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    with service.sessions.begin() as session:
        session.execute(update(Wallet).where(Wallet.id == UUID(source if disabled_side == "source" else target)).values(enabled=False))
    with pytest.raises(WalletDisabled):
        transfer(service, source, target)


def test_duplicate_returns_original_even_after_wallet_state_changes(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    result = transfer(service, source, target, key="same-key")
    before = counts(service)
    with service.sessions.begin() as session:
        session.execute(update(Wallet).where(Wallet.id == UUID(source)).values(enabled=False))
    assert transfer(service, source, target, key="same-key") == result
    assert counts(service) == before
    assert balance(service, source) == (1000, 0)


@pytest.mark.parametrize("change", ["amount", "target", "actor", "operation"])
def test_idempotency_conflicts(service, change):
    source, target, other = [participant(service).wallet_id for _ in range(3)]
    fund(service, source, 3000)
    transfer(service, source, target, key="conflict")
    before = counts(service)
    with pytest.raises(IdempotencyConflict):
        if change == "operation":
            service.create_refund_hold(wallet_id=source, amount_paise=1000, reason="test",
                                      idempotency_key="conflict", actor_reference="test-participant")
        else:
            service.transfer(source_wallet_id=source, target_wallet_id=other if change == "target" else target,
                             amount_paise=500 if change == "amount" else 1000, idempotency_key="conflict",
                             actor_reference="other-actor" if change == "actor" else "test-participant")
    assert counts(service) == before


def test_concurrent_spends_cannot_overspend(service, accounting_engine):
    source, first_target, second_target = [participant(service).wallet_id for _ in range(3)]
    fund(service, source, 2000)
    both_waiting, guard, waiting = Event(), Lock(), []

    def observe_locks(connection, cursor, statement, parameters, context, executemany):
        if "FROM wallets" in statement and "FOR UPDATE" in statement:
            with guard:
                waiting.append(True)
                if len(waiting) == 2:
                    both_waiting.set()

    def spend(target):
        try:
            return transfer(service, source, target, 1500)
        except InsufficientFunds:
            return None

    # Hold the sender in a third connection until BOTH spenders attempt their locks.
    with Session(accounting_engine) as blocker:
        blocker.execute(select(Wallet).where(Wallet.id == UUID(source)).with_for_update())
        event.listen(accounting_engine, "before_cursor_execute", observe_locks)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(spend, target) for target in (first_target, second_target)]
                try:
                    assert both_waiting.wait(8), "Both independent spend transactions must contend"
                finally:
                    blocker.rollback()
                results = [future.result(timeout=20) for future in futures]
        finally:
            event.remove(accounting_engine, "before_cursor_execute", observe_locks)
    assert sum(result is not None for result in results) == 1
    assert balance(service, source) == (500, 0)
    assert sum(balance(service, wallet)[0] for wallet in (first_target, second_target)) == 1500
    assert service.reconcile().reconciled


def test_concurrent_duplicate_is_only_applied_once(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    gate = Barrier(2)

    def spend():
        gate.wait(timeout=10)
        return transfer(service, source, target, 1500, key="parallel-retry")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(spend) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    assert balance(service, source) == (500, 0)
    assert balance(service, target) == (1500, 0)


def test_opposite_direction_transfers_use_consistent_lock_order(service):
    first, second = participant(service).wallet_id, participant(service).wallet_id
    fund(service, first, 2000)
    fund(service, second, 2000)
    gate = Barrier(2)

    def spend(source, target):
        gate.wait(timeout=10)
        return transfer(service, source, target, 1000)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(spend, first, second), pool.submit(spend, second, first)]
        for future in futures:
            future.result(timeout=20)
    assert balance(service, first) == balance(service, second) == (2000, 0)
    assert service.reconcile().reconciled


def test_failure_after_debit_rolls_everything_back_and_key_can_retry(service, accounting_engine):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    before, debit_was_written = counts(service), []

    def fail_credit(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO ledger_entries"):
            # _post flushes entries separately; inspect uncommitted projection before credit.
            if debit_was_written:
                assert connection.scalar(text("SELECT balance_paise FROM wallets WHERE id = :id"), {"id": UUID(source)}) == 1000
                raise RuntimeError("Injected failure before credit")
            debit_was_written.append(True)

    event.listen(accounting_engine, "before_cursor_execute", fail_credit)
    try:
        with pytest.raises(RuntimeError, match="Injected"):
            transfer(service, source, target, key="retry-after-rollback")
    finally:
        event.remove(accounting_engine, "before_cursor_execute", fail_credit)
    assert debit_was_written
    assert counts(service) == before
    assert balance(service, source) == (2000, 0)
    assert balance(service, target) == (0, 0)
    transfer(service, source, target, key="retry-after-rollback")
    assert service.reconcile().reconciled


def test_funding_verification_deduplication_and_limits(service):
    wallet = participant(service).wallet_id
    args = dict(wallet_id=wallet, amount_paise=5000, external_reference="deposit-1",
                verification_reference="synthetic-statement-line-1", verified_by="admin", idempotency_key="funding-1")
    first = service.credit_verified_funding(**args)
    assert service.credit_verified_funding(**args) == first
    with pytest.raises(DuplicateReference):
        service.credit_verified_funding(**{**args, "idempotency_key": "funding-2"})
    with pytest.raises(LimitExceeded):
        fund(service, wallet, 5001)
    with pytest.raises(InvalidRequest):
        service.credit_verified_funding(**{**args, "verification_reference": "", "idempotency_key": "funding-3"})
    with pytest.raises(IdempotencyConflict):
        service.credit_verified_funding(**{**args, "amount_paise": 1000})
    assert balance(service, wallet) == (5000, 0)


def test_concurrent_funding_respects_pool_cap(service):
    service.settings = service.settings.model_copy(update={"max_pool_reserve_paise": 10000})
    wallets = [participant(service).wallet_id for _ in range(2)]
    gate = Barrier(2)

    def credit(wallet):
        gate.wait(timeout=10)
        try:
            return fund(service, wallet, 6000)
        except LimitExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(credit, wallets))
    assert sum(result is not None for result in results) == 1
    assert service.reconcile().ledger_pool_paise == 6000


def test_refund_hold_release_is_compensating_and_idempotent(service):
    wallet, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, wallet, 3000)
    args = dict(wallet_id=wallet, amount_paise=2500, reason="test cancellation",
                actor_reference="admin", idempotency_key="hold")
    hold = service.create_refund_hold(**args)
    assert service.create_refund_hold(**args) == hold
    assert balance(service, wallet) == (3000, 2500)
    with pytest.raises(InsufficientFunds):
        transfer(service, wallet, target, 501)
    assert service.reconcile().reconciled
    release = service.release_refund_hold(refund_id=hold.refund_id, idempotency_key="release", actor_reference="admin")
    assert service.release_refund_hold(refund_id=hold.refund_id, idempotency_key="release", actor_reference="admin") == release
    assert balance(service, wallet) == (3000, 0)
    with service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(LedgerEntry)) == 3
    assert service.reconcile().reconciled


def test_refund_completion_reduces_balance_and_reserve_once(service):
    wallet = participant(service).wallet_id
    fund(service, wallet, 3000)
    hold = service.create_refund_hold(wallet_id=wallet, amount_paise=2500, reason="return funds",
                                      actor_reference="admin", idempotency_key="hold")
    with service.sessions.begin() as session:
        session.execute(update(Wallet).where(Wallet.id == UUID(wallet)).values(enabled=False))
    args = dict(refund_id=hold.refund_id, external_reference="external-refund-1",
                verification_reference="synthetic-bank-refund-record", verified_by="admin", idempotency_key="complete")
    result = service.record_completed_refund(**args)
    assert service.record_completed_refund(**args) == result
    assert balance(service, wallet) == (500, 0)
    assert service.reconcile().ledger_pool_paise == 500
    assert service.reconcile().reconciled
    with pytest.raises(InvalidRefundState):
        service.release_refund_hold(refund_id=hold.refund_id, idempotency_key="late-release", actor_reference="admin")
    with pytest.raises(InvalidRefundState):
        service.record_completed_refund(**{**args, "idempotency_key": "another-completion"})


def test_released_refund_cannot_complete(service):
    wallet = participant(service).wallet_id
    fund(service, wallet, 2000)
    hold = service.create_refund_hold(wallet_id=wallet, amount_paise=1000, reason="test", actor_reference="admin", idempotency_key="hold")
    service.release_refund_hold(refund_id=hold.refund_id, actor_reference="admin", idempotency_key="release")
    with pytest.raises(InvalidRefundState):
        service.record_completed_refund(refund_id=hold.refund_id, external_reference="external", verification_reference="verified-record",
                                        verified_by="admin", idempotency_key="complete")


def test_refund_hold_cannot_exceed_available(service):
    wallet = participant(service).wallet_id
    fund(service, wallet, 1000)
    with pytest.raises(InsufficientFunds):
        service.create_refund_hold(wallet_id=wallet, amount_paise=1001, reason="test", actor_reference="admin", idempotency_key="hold")


def test_reconciliation_detects_corruption_and_blocks_spending(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    with service.sessions.begin() as session:
        session.execute(update(Wallet).where(Wallet.id == UUID(source)).values(balance_paise=3000))
    report = service.reconcile()
    assert not report.reconciled
    mismatch = next(wallet for wallet in report.wallets if wallet.wallet_id == source)
    assert (mismatch.balance_paise, mismatch.ledger_balance_paise) == (3000, 2000)
    with pytest.raises(ReconciliationRequired):
        transfer(service, source, target)
    assert balance(service, source) == (3000, 0)  # Reconciliation does not silently rewrite evidence.


@pytest.mark.parametrize("table", ["ledger_entries", "financial_transactions", "funding_records", "audit_events", "idempotency_records"])
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_database_history_is_immutable(service, table, operation):
    wallet = participant(service).wallet_id
    fund(service, wallet, 1000)
    statements = {"UPDATE": f"UPDATE {table} SET created_at = created_at", "DELETE": f"DELETE FROM {table}",
                  "TRUNCATE": f"TRUNCATE {table} CASCADE"}
    with pytest.raises(IntegrityError):
        with service.sessions.begin() as session:
            session.execute(text(statements[operation]))
    assert balance(service, wallet) == (1000, 0)
    assert service.reconcile().reconciled


def test_database_rejects_unbalanced_transaction_at_commit(service):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    before = counts(service)
    with pytest.raises(IntegrityError, match="does not balance"):
        with service.sessions.begin() as session:
            # Missing credit would otherwise leave the debit projection changed.
            service._post(session, "transfer", 1000, UUID(source), UUID(target), [(UUID(source), -1000, 0)])
    assert counts(service) == before
    assert balance(service, source) == (2000, 0)


def test_migration_matches_models_and_is_repeatable(accounting_engine):
    with accounting_engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_authentication"
        command.downgrade(migration_config(connection), "0001_foundation")
        command.upgrade(migration_config(connection), "head")


@pytest.mark.parametrize("record_type", ["funding", "refund"])
def test_source_records_cannot_reference_wrong_transaction_type(service, record_type):
    source, target = participant(service).wallet_id, participant(service).wallet_id
    fund(service, source, 2000)
    hold = service.create_refund_hold(wallet_id=source, amount_paise=500, reason="test",
                                      actor_reference="admin", idempotency_key="hold")
    payment = transfer(service, source, target, 500)
    with pytest.raises(IntegrityError, match="matching financial"):
        with service.sessions.begin() as session:
            if record_type == "funding":
                session.add(FundingRecord(wallet_id=UUID(target), transaction_id=UUID(payment.transaction_id),
                    amount_paise=500, external_reference="wrong-kind", verification_reference="test", verified_by="test"))
            else:
                session.execute(update(RefundRecord).where(RefundRecord.id == UUID(hold.refund_id))
                    .values(status="released", release_transaction_id=UUID(payment.transaction_id)))
    assert balance(service, source) == (1500, 500)
    assert service.reconcile().reconciled


def test_migration_refuses_to_erase_history(service, accounting_engine):
    participant(service)
    with pytest.raises(RuntimeError, match="existing records"):
        with accounting_engine.begin() as connection:
            command.downgrade(migration_config(connection), "0001_foundation")
    with service.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Participant)) == 1

