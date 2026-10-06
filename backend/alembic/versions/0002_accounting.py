"""Integer-paise accounting, immutable history, and database ledger checks."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_accounting"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def identity() -> list[sa.Column]:
    return [sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def wallet_fk(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("wallets.id"), nullable=nullable)


def transaction_fk(name: str, nullable: bool = False, unique: bool = True) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("financial_transactions.id"), nullable=nullable, unique=unique)


def upgrade() -> None:
    op.create_table("participants", *identity(),
        sa.Column("external_reference", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False))
    op.create_table("wallets", *identity(),
        sa.Column("participant_id", sa.Uuid(), sa.ForeignKey("participants.id"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("balance_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("held_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("balance_paise >= 0", name="wallet_balance_nonnegative"),
        sa.CheckConstraint("held_paise >= 0 AND held_paise <= balance_paise", name="wallet_hold_bounds"))
    op.create_table("financial_transactions", *identity(),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        wallet_fk("source_wallet_id", True), wallet_fk("target_wallet_id", True),
        sa.CheckConstraint("amount_paise > 0", name="transaction_amount_positive"),
        sa.CheckConstraint(
            "(kind = 'funding' AND source_wallet_id IS NULL AND target_wallet_id IS NOT NULL) OR "
            "(kind = 'transfer' AND source_wallet_id IS NOT NULL AND target_wallet_id IS NOT NULL "
            "AND source_wallet_id <> target_wallet_id) OR "
            "(kind IN ('refund_hold', 'refund_release', 'refund_complete') "
            "AND source_wallet_id IS NOT NULL AND target_wallet_id IS NULL)", name="transaction_shape"))
    for column in ("source_wallet_id", "target_wallet_id"):
        op.create_index(f"ix_financial_transactions_{column}", "financial_transactions", [column])
    op.create_table("ledger_entries", *identity(),
        transaction_fk("transaction_id", unique=False), wallet_fk("wallet_id"),
        sa.Column("balance_delta_paise", sa.BigInteger(), nullable=False),
        sa.Column("held_delta_paise", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("transaction_id", "wallet_id", name="ledger_transaction_wallet_unique"),
        sa.CheckConstraint("balance_delta_paise <> 0 OR held_delta_paise <> 0", name="ledger_nonzero"))
    op.create_index("ix_ledger_wallet_created", "ledger_entries", ["wallet_id", "created_at"])
    op.create_table("funding_records", *identity(), wallet_fk("wallet_id"), transaction_fk("transaction_id"),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("external_reference", sa.String(128), nullable=False, unique=True),
        sa.Column("verification_reference", sa.String(256), nullable=False),
        sa.Column("verified_by", sa.String(128), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("amount_paise > 0", name="funding_amount_positive"))
    op.create_index("ix_funding_records_wallet_id", "funding_records", ["wallet_id"])
    op.create_table("refund_records", *identity(), wallet_fk("wallet_id"),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="held"),
        sa.Column("reason", sa.String(256), nullable=False),
        transaction_fk("hold_transaction_id"), transaction_fk("release_transaction_id", True),
        transaction_fk("completion_transaction_id", True),
        sa.Column("external_reference", sa.String(128), unique=True),
        sa.Column("verification_reference", sa.String(256)), sa.Column("verified_by", sa.String(128)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_paise > 0", name="refund_amount_positive"),
        sa.CheckConstraint(
            "(status = 'held' AND release_transaction_id IS NULL AND completion_transaction_id IS NULL "
            "AND external_reference IS NULL AND verification_reference IS NULL AND verified_by IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'released' AND release_transaction_id IS NOT NULL AND completion_transaction_id IS NULL "
            "AND external_reference IS NULL AND verification_reference IS NULL AND verified_by IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND release_transaction_id IS NULL AND completion_transaction_id IS NOT NULL "
            "AND external_reference IS NOT NULL AND verification_reference IS NOT NULL AND verified_by IS NOT NULL "
            "AND completed_at IS NOT NULL)", name="refund_state_shape"))
    op.create_index("ix_refund_records_wallet_id", "refund_records", ["wallet_id"])
    op.create_table("audit_events", *identity(),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("actor_reference", sa.String(128), nullable=False),
        transaction_fk("transaction_id", True, False), sa.Column("details", postgresql.JSONB(), nullable=False))
    op.create_index("ix_audit_events_transaction_id", "audit_events", ["transaction_id"])
    op.create_table("idempotency_records",
        sa.Column("key", sa.String(128), primary_key=True), sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("result", postgresql.JSONB(), nullable=False),
        transaction_fk("transaction_id", True, False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_idempotency_records_transaction_id", "idempotency_records", ["transaction_id"])

    op.execute("""
        CREATE FUNCTION reject_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Accounting history is append-only; use compensating entries'
                USING ERRCODE = '23514';
        END $$
    """)
    for table in ("ledger_entries", "financial_transactions", "funding_records", "audit_events", "idempotency_records"):
        op.execute(f"CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION reject_history_change()")
        op.execute(f"CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION reject_history_change()")
    op.execute("CREATE TRIGGER immutable_delete BEFORE DELETE ON refund_records "
               "FOR EACH ROW EXECUTE FUNCTION reject_history_change()")
    op.execute("CREATE TRIGGER immutable_truncate BEFORE TRUNCATE ON refund_records "
               "FOR EACH STATEMENT EXECUTE FUNCTION reject_history_change()")
    op.execute("""
        CREATE FUNCTION guard_refund_transition() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status <> 'held' OR NEW.status NOT IN ('released', 'completed') OR
               ROW(NEW.id, NEW.wallet_id, NEW.amount_paise, NEW.reason, NEW.hold_transaction_id, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.wallet_id, OLD.amount_paise, OLD.reason, OLD.hold_transaction_id, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Invalid refund transition' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER refund_transition BEFORE UPDATE ON refund_records "
               "FOR EACH ROW EXECUTE FUNCTION guard_refund_transition()")
    op.execute("""
        CREATE FUNCTION apply_ledger_projection() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE wallets SET balance_paise = balance_paise + NEW.balance_delta_paise,
                               held_paise = held_paise + NEW.held_delta_paise
            WHERE id = NEW.wallet_id;
            RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER ledger_projection AFTER INSERT ON ledger_entries "
               "FOR EACH ROW EXECUTE FUNCTION apply_ledger_projection()")
    op.execute("""
        CREATE FUNCTION validate_transaction_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            txn financial_transactions%ROWTYPE;
            txn_id uuid;
            entry_count integer;
            matching_count integer;
            expected_count integer;
            record_matches boolean := true;
        BEGIN
            IF TG_TABLE_NAME = 'financial_transactions' THEN txn_id := NEW.id;
            ELSE txn_id := NEW.transaction_id; END IF;
            SELECT * INTO STRICT txn FROM financial_transactions WHERE id = txn_id;
            expected_count := CASE WHEN txn.kind = 'transfer' THEN 2 ELSE 1 END;
            SELECT count(*), count(*) FILTER (WHERE
                (txn.kind = 'transfer' AND held_delta_paise = 0 AND
                    ((wallet_id = txn.source_wallet_id AND balance_delta_paise = -txn.amount_paise) OR
                     (wallet_id = txn.target_wallet_id AND balance_delta_paise = txn.amount_paise))) OR
                (txn.kind = 'funding' AND wallet_id = txn.target_wallet_id AND
                    balance_delta_paise = txn.amount_paise AND held_delta_paise = 0) OR
                (txn.kind = 'refund_hold' AND wallet_id = txn.source_wallet_id AND
                    balance_delta_paise = 0 AND held_delta_paise = txn.amount_paise) OR
                (txn.kind = 'refund_release' AND wallet_id = txn.source_wallet_id AND
                    balance_delta_paise = 0 AND held_delta_paise = -txn.amount_paise) OR
                (txn.kind = 'refund_complete' AND wallet_id = txn.source_wallet_id AND
                    balance_delta_paise = -txn.amount_paise AND held_delta_paise = -txn.amount_paise)
            ) INTO entry_count, matching_count FROM ledger_entries WHERE transaction_id = txn.id;
            IF txn.kind = 'funding' THEN
                SELECT EXISTS(SELECT 1 FROM funding_records WHERE transaction_id = txn.id
                    AND wallet_id = txn.target_wallet_id AND amount_paise = txn.amount_paise) INTO record_matches;
            ELSIF txn.kind = 'refund_hold' THEN
                SELECT EXISTS(SELECT 1 FROM refund_records WHERE hold_transaction_id = txn.id
                    AND wallet_id = txn.source_wallet_id AND amount_paise = txn.amount_paise) INTO record_matches;
            ELSIF txn.kind = 'refund_release' THEN
                SELECT EXISTS(SELECT 1 FROM refund_records WHERE release_transaction_id = txn.id
                    AND status = 'released' AND wallet_id = txn.source_wallet_id
                    AND amount_paise = txn.amount_paise) INTO record_matches;
            ELSIF txn.kind = 'refund_complete' THEN
                SELECT EXISTS(SELECT 1 FROM refund_records WHERE completion_transaction_id = txn.id
                    AND status = 'completed' AND wallet_id = txn.source_wallet_id
                    AND amount_paise = txn.amount_paise) INTO record_matches;
            END IF;
            IF entry_count <> expected_count OR matching_count <> expected_count OR NOT record_matches THEN
                RAISE EXCEPTION 'Transaction ledger or source record does not balance'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    for table in ("financial_transactions", "ledger_entries"):
        op.execute(f"CREATE CONSTRAINT TRIGGER balanced_transaction AFTER INSERT ON {table} "
                   "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_transaction_ledger()")

    op.execute("""
        CREATE FUNCTION validate_source_record() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE valid boolean;
        BEGIN
            IF TG_TABLE_NAME = 'funding_records' THEN
                SELECT EXISTS(SELECT 1 FROM financial_transactions WHERE id = NEW.transaction_id
                    AND kind = 'funding' AND target_wallet_id = NEW.wallet_id
                    AND amount_paise = NEW.amount_paise) INTO valid;
            ELSE
                SELECT EXISTS(SELECT 1 FROM financial_transactions WHERE id = NEW.hold_transaction_id
                    AND kind = 'refund_hold' AND source_wallet_id = NEW.wallet_id
                    AND amount_paise = NEW.amount_paise) INTO valid;
                IF NEW.status = 'released' THEN
                    valid := valid AND EXISTS(SELECT 1 FROM financial_transactions
                        WHERE id = NEW.release_transaction_id AND kind = 'refund_release'
                        AND source_wallet_id = NEW.wallet_id AND amount_paise = NEW.amount_paise);
                ELSIF NEW.status = 'completed' THEN
                    valid := valid AND EXISTS(SELECT 1 FROM financial_transactions
                        WHERE id = NEW.completion_transaction_id AND kind = 'refund_complete'
                        AND source_wallet_id = NEW.wallet_id AND amount_paise = NEW.amount_paise);
                END IF;
            END IF;
            IF NOT valid THEN
                RAISE EXCEPTION 'Source record must reference matching financial transactions'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NULL;
        END $$
    """)
    op.execute("CREATE CONSTRAINT TRIGGER matching_source_record AFTER INSERT ON funding_records "
               "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_source_record()")
    op.execute("CREATE CONSTRAINT TRIGGER matching_source_record AFTER INSERT OR UPDATE ON refund_records "
               "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_source_record()")


def downgrade() -> None:
    # A migration rollback must not erase financial or audit history.
    tables = ("idempotency_records", "audit_events", "refund_records", "funding_records",
              "ledger_entries", "financial_transactions", "wallets", "participants")
    # Prevent a concurrent writer from creating history between the checks and DROP.
    op.execute("LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE")
    for table in tables:
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("Cannot downgrade accounting with existing records; use a forward migration")
    for table in tables:
        op.drop_table(table)
    for function in ("validate_source_record", "validate_transaction_ledger", "apply_ledger_projection", "guard_refund_transition", "reject_history_change"):
        op.execute(f"DROP FUNCTION {function}()")
