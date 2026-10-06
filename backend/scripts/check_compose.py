"""Disposable Docker integration check. Never uses the demonstration project or .env."""

import json
import base64
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    project = "offlinewallet-test-" + secrets.token_hex(6)
    environment = os.environ.copy()
    environment.update(
        DB_NAME="offlinewallet_test",
        DB_USER="wallet_runtime",
        DB_ADMIN_USER="offlinewallet_test",
        DB_ADMIN_PASSWORD=secrets.token_hex(32),
        MIGRATION_DB_PASSWORD=secrets.token_hex(32),
        DEVICE_MASTER_KEY=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        DB_PASSWORD=secrets.token_hex(32),
        BACKEND_PORT="0",
        MAX_WALLET_BALANCE_PAISE="10000",
        MAX_PAYMENT_PAISE="2000",
        MAX_POOL_RESERVE_PAISE="50000",
    )
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        env_file = Path(directory) / "empty.env"
        env_file.touch()
        test_config = Path(directory) / "checks.json"
        test_config.write_text(json.dumps({"services": {"ledger-tests": {
            "build": {"context": str(ROOT / "backend"), "target": "test"},
            "environment": {
                "LEDGER_TEST_ISOLATED": "1", "LEDGER_TEST_DB_HOST": "db",
                "LEDGER_TEST_DB_NAME": "offlinewallet_test", "LEDGER_TEST_DB_USER": "offlinewallet_test",
                "LEDGER_TEST_DB_PASSWORD": "${DB_ADMIN_PASSWORD}",
                "LEDGER_TEST_RUNTIME_PASSWORD": "${DB_PASSWORD}",
                "LEDGER_TEST_MIGRATION_PASSWORD": "${MIGRATION_DB_PASSWORD}",
            },
            "depends_on": {"db": {"condition": "service_healthy"}}, "profiles": ["checks"],
        }}}), encoding="utf-8")
        command = [
            "docker", "compose", "--progress", "plain", "--env-file", str(env_file),
            "-f", str(ROOT / "compose.yaml"), "-f", str(test_config), "-p", project,
        ]

        def compose(*args: str, capture: bool = False) -> str:
            result = subprocess.run(
                [*command, *args], cwd=ROOT, env=environment, check=True,
                text=True, stdout=subprocess.PIPE if capture else None,
            )
            return result.stdout or ""

        try:
            compose("config", "--quiet")
            compose("up", "--build", "--detach", "--wait", "--wait-timeout", "120")
            address = compose("port", "backend", "8000", capture=True).strip()

            def check(path: str, expected_status: int, expected_body: dict[str, str]) -> None:
                try:
                    response = urllib.request.urlopen(f"http://{address}{path}", timeout=15)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    assert response.status == expected_status, (path, response.status)
                    assert json.load(response) == expected_body, path
                print(f"PASS {path}: HTTP {expected_status}", flush=True)

            check("/health", 200, {"status": "ok"})
            check("/health/ready", 200, {"status": "ready", "database": "ok"})
            revision = compose("exec", "-T", "db", "psql", "-U", "offlinewallet_test", "-d",
                               "offlinewallet_test", "-Atc", "SELECT version_num FROM alembic_version", capture=True)
            assert revision.strip() == "0003_authentication"
            privileges = compose("exec", "-T", "db", "psql", "-U", "offlinewallet_test", "-d",
                "offlinewallet_test", "-Atc", "SELECT pg_get_userbyid(nspowner), "
                "has_schema_privilege('wallet_runtime','public','USAGE'), "
                "has_schema_privilege('wallet_runtime','public','CREATE'), "
                "has_table_privilege('wallet_runtime','public.alembic_version','SELECT') "
                "FROM pg_namespace WHERE nspname='public'", capture=True)
            assert privileges.strip() == "wallet_migrator|t|f|f", privileges
            tables = compose(
                "exec", "-T", "db", "psql", "-U", "offlinewallet_test",
                "-d", "offlinewallet_test", "-Atc",
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename",
                capture=True,
            )
            assert set(tables.split()) == {
                "alembic_version", "participants", "wallets", "financial_transactions", "ledger_entries",
                "funding_records", "refund_records", "audit_events", "idempotency_records",
                "accounts", "devices", "enrollment_tokens", "auth_sessions", "auth_rate_buckets",
            }, tables
            compose("run", "--build", "--rm", "ledger-tests")
            counts = compose(
                "exec", "-T", "db", "psql", "-U", "offlinewallet_test", "-d", "offlinewallet_test", "-Atc",
                "SELECT (SELECT count(*) FROM public.wallets), (SELECT count(*) FROM public.ledger_entries)",
                capture=True,
            )
            assert counts.strip() == "0|0", counts
            print("PASS migration at head; tests left public wallets and ledger empty", flush=True)
            compose("stop", "db")
            check("/health/ready", 503, {"status": "not_ready", "database": "unavailable"})
            check("/health", 200, {"status": "ok"})
            compose("start", "db")
            for attempt in range(20):
                try:
                    check("/health/ready", 200, {"status": "ready", "database": "ok"})
                    break
                except (AssertionError, urllib.error.URLError):
                    if attempt == 19:
                        raise
                    time.sleep(1)
            print("PASS database recovery", flush=True)
        finally:
            # Only the randomly named test project above is ever removed.
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
