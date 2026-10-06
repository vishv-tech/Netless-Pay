"""Local provisioning and least-privilege grants. Never logs credentials."""
import os

from psycopg import connect, sql
from sqlalchemy import text

from app.config import Settings

TABLES = ("participants", "wallets", "financial_transactions", "ledger_entries", "funding_records",
          "refund_records", "audit_events", "idempotency_records", "accounts", "devices",
          "enrollment_tokens", "auth_sessions", "auth_rate_buckets")
FUNCTIONS = ("reject_history_change", "guard_refund_transition", "apply_ledger_projection",
             "validate_transaction_ledger", "validate_source_record", "guard_account_role", "guard_device_history")


def grant_runtime(connection):
    # Operates only on the current schema (public in deployment, random schema in tests).
    schema = connection.scalar(text("SELECT current_schema()"))
    quoted = connection.dialect.identifier_preparer.quote_identifier(schema)
    connection.execute(text(f"REVOKE ALL ON SCHEMA {quoted} FROM PUBLIC"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA {quoted} TO wallet_runtime"))
    for table in (*TABLES, "alembic_version"):
        connection.execute(text(f"REVOKE ALL ON {table} FROM PUBLIC, wallet_runtime"))
    for table in TABLES:
        if table not in ("funding_records", "refund_records", "idempotency_records"):
            connection.execute(text(f"GRANT SELECT ON {table} TO wallet_runtime"))
    for table in ("participants", "audit_events", "accounts", "devices", "enrollment_tokens", "auth_sessions", "auth_rate_buckets"):
        connection.execute(text(f"GRANT INSERT ON {table} TO wallet_runtime"))
    connection.execute(text("GRANT INSERT (id, participant_id) ON wallets TO wallet_runtime"))
    columns = {
        "wallets": "enabled", "accounts": "password_hash, password_changed_at, status",
        "devices": "status, revoked_at, last_seen_at, approved_by, approved_at",
        "enrollment_tokens": "redeemed_at, revoked_at", "auth_sessions": "revoked_at, device_id",
        "auth_rate_buckets": "window_started_at, attempts",
    }
    for table, names in columns.items():
        connection.execute(text(f"GRANT UPDATE ({names}) ON {table} TO wallet_runtime"))
    for name in FUNCTIONS:
        connection.execute(text(f"REVOKE ALL ON FUNCTION {name}() FROM PUBLIC, wallet_runtime"))


def provision():
    settings = Settings()
    with connect(host=settings.db_host, port=settings.db_port, dbname=settings.db_name,
                 user=settings.db_user, password=settings.db_password.get_secret_value()) as connection:
        with connection.cursor() as cursor:
            for name, variable in (("wallet_migrator", "MIGRATION_DB_PASSWORD"), ("wallet_runtime", "RUNTIME_DB_PASSWORD")):
                secret = os.environ[variable]
                if len(secret) < 24:
                    raise ValueError("Local database role passwords must be at least 24 characters")
                if not cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone():
                    cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(name)))
                cursor.execute(sql.SQL("ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}")
                               .format(sql.Identifier(name), sql.Literal(secret)))
            cursor.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(settings.db_name)))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO wallet_runtime, wallet_migrator").format(sql.Identifier(settings.db_name)))
            cursor.execute("ALTER SCHEMA public OWNER TO wallet_migrator")
            cursor.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            # Transfer only known application objects when upgrading an existing Sprint 1 volume.
            for table in (*TABLES, "alembic_version"):
                if cursor.execute("SELECT to_regclass(%s)", ("public." + table,)).fetchone()[0]:
                    cursor.execute(sql.SQL("ALTER TABLE public.{} OWNER TO wallet_migrator").format(sql.Identifier(table)))
            for name in FUNCTIONS:
                if cursor.execute("SELECT to_regprocedure(%s)", ("public." + name + "()",)).fetchone()[0]:
                    cursor.execute(sql.SQL("ALTER FUNCTION public.{}() OWNER TO wallet_migrator").format(sql.Identifier(name)))
    print("Local database roles configured; no credentials printed.")


if __name__ == "__main__":
    try:
        provision()
    except Exception:
        raise SystemExit("Database role setup failed; check local configuration and database administrator access.") from None
