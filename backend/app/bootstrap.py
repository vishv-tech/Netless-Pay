"""Explicit local operator bootstrap; passwords are never command-line arguments."""
import argparse
from getpass import getpass, GetPassWarning
import re
import warnings

from sqlalchemy import select, text

from app.auth_models import Account
from app.auth_service import audit, now
from app.config import Settings
from app.database import build_engine, build_session_factory
from app.security import PASSWORDS, check_password_policy


def create_first_admin(engine, username, password):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{2,63}", username):
        raise ValueError("Administrator name must be 3-64 lowercase letters, digits, dot, hyphen or underscore")
    check_password_policy(password)
    with build_session_factory(engine).begin() as session:
        session.execute(text("SELECT pg_advisory_xact_lock(735419021)"))
        if session.scalar(select(Account.id).where(Account.role == "ADMIN")):
            raise ValueError("An administrator already exists; bootstrap cannot create another")
        account = Account(role="ADMIN", status="active", login_name=username,
                          password_hash=PASSWORDS.hash(password), password_changed_at=now())
        session.add(account)
        session.flush()
        audit(session, "admin.bootstrapped", account.id, account_id=str(account.id), role="ADMIN")
        return account.id


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            # Do not echo mistakenly supplied credential arguments into terminal logs.
            self.print_usage()
            self.exit(2, "Invalid arguments; use create-admin with no password arguments.\n")

    parser = SafeParser(description="Interactively create the first administrator")
    parser.add_argument("command", choices=["create-admin"])
    parser.parse_args()
    warnings.filterwarnings("error", category=GetPassWarning)
    username = input("Administrator username: ")
    try:
        password = getpass("Password (12-128 characters; letter and non-letter): ")
        if password != getpass("Confirm password: "):
            raise SystemExit("Passwords did not match")
    except GetPassWarning:
        raise SystemExit("A terminal with hidden password input is required") from None
    engine = build_engine(Settings())
    try:
        create_first_admin(engine, username, password)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception:
        raise SystemExit("Bootstrap failed; use migration credentials and check database readiness") from None
    finally:
        engine.dispose()
    print("First administrator created. Sign in through /api/v1/admin/login.")


if __name__ == "__main__":
    main()
