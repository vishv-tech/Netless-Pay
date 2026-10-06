"""Authentication tests use only random schemas in the disposable PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import logging
import os
from uuid import UUID, uuid4

from alembic import command
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.accounting import AccountingService
from app.auth_models import Account, AuthSession, Device, EnrollmentToken
from app.auth_service import AuthError, AuthService, now
from app.bootstrap import create_first_admin
from app.db_roles import TABLES, grant_runtime
from app.main import create_app
from app.models import AuditEvent, Wallet
from app.security import PASSWORDS, token_hash
from conftest import migration_config
from test_accounting import fund

pytestmark = pytest.mark.postgres
PASSWORD = "Synthetic-river-7-stones"
SECOND_PASSWORD = "Synthetic-cloud-8-trees"


def headers(token):
    return {"Authorization": "Bearer " + token}


@pytest.fixture
def auth_env(accounting_engine, settings):
    with accounting_engine.begin() as connection:
        grant_runtime(connection)
        schema = connection.scalar(text("SELECT current_schema()"))
    runtime = create_engine(accounting_engine.url.set(username="wallet_runtime",
        password=os.environ["LEDGER_TEST_RUNTIME_PASSWORD"]), hide_parameters=True,
        connect_args={"options": f"-c search_path={schema} -c statement_timeout=15000"})
    create_first_admin(accounting_engine, "test-admin", PASSWORD)
    auth = AuthService(runtime, settings)
    with TestClient(create_app(settings, runtime)) as client:
        response = client.post("/api/v1/admin/login", json={"username": "test-admin", "password": PASSWORD})
        assert response.status_code == 200, response.text
        yield client, auth, accounting_engine, response.json()["session_token"]
    runtime.dispose()


def enroll(env, phone="9876543210"):
    client, _, _, admin = env
    response = client.post("/api/v1/admin/participants", headers=headers(admin),
        json={"name": "Synthetic participant", "phone": phone, "admin_confirmed_phone": True})
    assert response.status_code == 201, response.text
    return response.json()


def activate(env, phone="9876543210"):
    enrollment = enroll(env, phone)
    response = env[0].post("/api/v1/auth/redeem", json={"enrollment_token": enrollment["enrollment_token"], "password": PASSWORD})
    assert response.status_code == 204, response.text
    login = env[0].post("/api/v1/auth/login", json={"phone": phone, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return enrollment, login.json()["session_token"]


def approved_device(env, token):
    client, _, _, admin = env
    response = client.post("/api/v1/me/devices", headers=headers(token), json={"label": "Test device"})
    assert response.status_code == 201, response.text
    device = response.json()
    response = client.post(f'/api/v1/admin/devices/{device["device_id"]}/approve', headers=headers(admin))
    assert response.status_code == 200, response.text
    return device


def test_enrollment_activation_and_manual_confirmation(auth_env):
    enrollment, token = activate(auth_env, "+91 (98765) 43210")
    client, _, engine, _ = auth_env
    profile = client.get("/api/v1/me", headers=headers(token)).json()
    assert profile["phone"] == "+919876543210"
    assert profile["phone_confirmation"] == "admin-confirmed phone"
    with Session(engine) as session:
        account = session.get(Account, UUID(enrollment["account_id"]))
        assert account.status == "active"
        assert account.password_hash.startswith("$argon2id$")
        assert PASSWORDS.verify(account.password_hash, PASSWORD)
        wallet = session.scalar(select(Wallet).where(Wallet.participant_id == account.participant_id))
        assert wallet.balance_paise == wallet.held_paise == 0
    assert client.get("/api/v1/me/wallet", headers=headers(token)).status_code == 403


@pytest.mark.parametrize("mode", ["expired", "reused", "revoked", "altered", "wrong"])
def test_unavailable_enrollment(auth_env, mode):
    enrollment = enroll(auth_env)
    client, _, engine, admin = auth_env
    raw = enrollment["enrollment_token"]
    if mode == "expired":
        with engine.begin() as connection:
            connection.execute(update(EnrollmentToken).values(expires_at=now()-timedelta(seconds=1)))
    elif mode == "reused":
        assert client.post("/api/v1/auth/redeem", json={"enrollment_token": raw, "password": PASSWORD}).status_code == 204
    elif mode == "revoked":
        assert client.delete(f'/api/v1/admin/participants/{enrollment["participant_id"]}/enrollment', headers=headers(admin)).status_code == 204
    else:
        raw = raw + "x" if mode == "altered" else "unknown-token"
    response = client.post("/api/v1/auth/redeem", json={"enrollment_token": raw, "password": PASSWORD})
    assert response.status_code == 400
    assert response.json() == {"detail": "Enrollment unavailable"}


def test_reissue_revokes_previous_token(auth_env):
    enrollment = enroll(auth_env)
    client, _, _, admin = auth_env
    response = client.post(f'/api/v1/admin/participants/{enrollment["participant_id"]}/enrollment', headers=headers(admin))
    assert response.status_code == 200
    assert client.post("/api/v1/auth/redeem", json={"enrollment_token": enrollment["enrollment_token"], "password": PASSWORD}).status_code == 400
    assert client.post("/api/v1/auth/redeem", json={"enrollment_token": response.json()["enrollment_token"], "password": PASSWORD}).status_code == 204


def test_concurrent_redemption_single_use(auth_env):
    enrollment = enroll(auth_env)
    auth = auth_env[1]
    def redeem(_):
        try:
            auth.redeem(enrollment["enrollment_token"], PASSWORD, "concurrent")
            return 204
        except AuthError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, range(2))) == [204, 400]


def test_login_generic_errors_and_pending_rejection(auth_env):
    client = auth_env[0]
    enroll(auth_env)
    responses = [client.post("/api/v1/auth/login", json={"phone": phone, "password": PASSWORD})
                 for phone in ("9876543210", "8765432109", "invalid")]
    assert all(r.status_code == 401 for r in responses)
    assert len({r.text for r in responses}) == 1
    _, token = activate(auth_env, "8765432109")
    assert client.get("/api/v1/me", headers=headers(token)).status_code == 200
    wrong = client.post("/api/v1/auth/login", json={"phone": "8765432109", "password": "incorrect"})
    assert wrong.status_code == 401 and wrong.text == responses[0].text


@pytest.mark.parametrize("operation", ["login", "redeem"])
def test_rate_limit_persists_failed_attempts_and_ignores_forwarded_ip(auth_env, operation):
    client = auth_env[0]
    path = "/api/v1/auth/" + operation
    body = {"phone": "9876543210", "password": PASSWORD} if operation == "login" else {"enrollment_token": "wrong", "password": PASSWORD}
    for index in range(5):
        assert client.post(path, json=body, headers={"X-Forwarded-For": str(index)}).status_code in (400, 401)
    assert client.post(path, json=body, headers={"X-Forwarded-For": "different"}).status_code == 429
    # A new service instance shares the same PostgreSQL counters.
    auth = AuthService(auth_env[2], auth_env[1].settings)
    with pytest.raises(AuthError) as error:
        if operation == "login":
            auth.login("9876543210", PASSWORD, "different-ip")
        else:
            auth.redeem("wrong", PASSWORD, "different-ip")
    assert error.value.status == 429


@pytest.mark.parametrize("mode", ["expiry", "logout", "logout-all"])
def test_session_expiration_and_revocation(auth_env, mode):
    _, token = activate(auth_env)
    client, auth, engine, _ = auth_env
    second = auth.login("9876543210", PASSWORD, "test").session_token
    if mode == "expiry":
        with engine.begin() as connection:
            connection.execute(update(AuthSession).where(AuthSession.token_hash == token_hash("session", token)).values(expires_at=now()-timedelta(seconds=1)))
    else:
        assert client.post("/api/v1/auth/" + mode, headers=headers(token)).status_code == 204
    assert client.get("/api/v1/me", headers=headers(token)).status_code == 401
    assert client.get("/api/v1/me", headers=headers(second)).status_code == (401 if mode == "logout-all" else 200)


def test_password_change_revokes_all_sessions(auth_env):
    _, token = activate(auth_env)
    client, auth, _, _ = auth_env
    second = auth.login("9876543210", PASSWORD, "test").session_token
    assert client.post("/api/v1/auth/password", headers=headers(token), json={"current_password": "wrong", "new_password": SECOND_PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/password", headers=headers(token), json={"current_password": PASSWORD, "new_password": SECOND_PASSWORD}).status_code == 204
    for raw in (token, second):
        assert client.get("/api/v1/me", headers=headers(raw)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": PASSWORD}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": SECOND_PASSWORD}).status_code == 200


def test_suspension_reactivation_and_wallet_disabled(auth_env):
    enrollment, token = activate(auth_env)
    device = approved_device(auth_env, token)
    client, auth, engine, admin = auth_env
    path = f'/api/v1/admin/participants/{enrollment["participant_id"]}/status'
    assert client.patch(path, headers=headers(admin), json={"status": "suspended"}).status_code == 204
    assert client.get("/api/v1/me", headers=headers(token)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": PASSWORD}).status_code == 401
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(device["device_id"]), device["device_secret"])
    with Session(engine) as session:
        assert not session.scalar(select(Wallet.enabled))
    assert client.patch(path, headers=headers(admin), json={"status": "active"}).status_code == 204
    assert client.get("/api/v1/me", headers=headers(token)).status_code == 401
    assert client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": PASSWORD}).status_code == 200


def test_device_registration_approval_replacement_and_secret_once(auth_env):
    enrollment, token = activate(auth_env)
    client, auth, engine, admin = auth_env
    first = client.post("/api/v1/me/devices", headers=headers(token), json={"label": "Phone"}).json()
    assert first["status"] == "pending" and len(first["device_secret"]) >= 40
    assert client.get("/api/v1/me/wallet", headers=headers(token)).status_code == 403
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(first["device_id"]), first["device_secret"])
    assert client.post(f'/api/v1/admin/devices/{first["device_id"]}/approve', headers=headers(admin)).status_code == 200
    assert client.get("/api/v1/me/wallet", headers=headers(token)).json()["balance_paise"] == 0
    assert str(auth.authenticate_device(UUID(first["device_id"]), first["device_secret"])) == enrollment["participant_id"]
    login = client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": PASSWORD,
        "device_id": first["device_id"], "device_secret": first["device_secret"]})
    assert login.status_code == 200
    second = client.post("/api/v1/me/devices", headers=headers(token), json={"label": "Replacement"}).json()
    assert second["secret_version"] == 2 and second["device_secret"] != first["device_secret"]
    assert client.get("/api/v1/me", headers=headers(login.json()["session_token"])).status_code == 401
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(first["device_id"]), first["device_secret"])
    for path, raw in (("/api/v1/me/devices", token), (f'/api/v1/admin/participants/{enrollment["participant_id"]}/devices', admin)):
        listed = client.get(path, headers=headers(raw))
        assert listed.status_code == 200
        assert "device_secret" not in listed.text and "encrypted_secret" not in listed.text
        assert listed.json()["total"] == 2
    assert client.post(f'/api/v1/admin/devices/{second["device_id"]}/approve', headers=headers(admin)).status_code == 200
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(second["device_id"]), first["device_secret"])


@pytest.mark.parametrize("admin_revoke", [True, False])
def test_revoked_device_rejected_everywhere(auth_env, admin_revoke):
    _, token = activate(auth_env)
    device = approved_device(auth_env, token)
    client, auth, engine, admin = auth_env
    path = ("/api/v1/admin/devices/" if admin_revoke else "/api/v1/me/devices/") + device["device_id"]
    assert client.delete(path, headers=headers(admin if admin_revoke else token)).status_code == 200
    assert client.get("/api/v1/me/wallet", headers=headers(token)).status_code == 401
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(device["device_id"]), device["device_secret"])
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(update(Device).where(Device.id == UUID(device["device_id"])).values(status="active", revoked_at=None))


def test_participant_ownership_and_history_pagination(auth_env):
    first, token = activate(auth_env)
    second, other = activate(auth_env, "8765432109")
    first_device, second_device = approved_device(auth_env, token), approved_device(auth_env, other)
    client, _, engine, _ = auth_env
    with Session(engine) as session:
        wallet = session.scalar(select(Wallet.id).where(Wallet.participant_id == UUID(first["participant_id"])))
    accounting = AccountingService(engine, auth_env[1].settings)
    for _ in range(3):
        fund(accounting, wallet, 100)
    assert client.get("/api/v1/me/wallet", headers=headers(token)).json()["balance_paise"] == 300
    assert client.get("/api/v1/me/wallet", headers=headers(other)).json()["balance_paise"] == 0
    pages = [client.get(f"/api/v1/me/transactions?limit=2&offset={offset}", headers=headers(token)).json() for offset in (0, 2)]
    assert [len(p["items"]) for p in pages] == [2, 1]
    assert pages[0]["total"] == 3
    assert len({item["transaction_id"] for p in pages for item in p["items"]}) == 3
    assert client.get("/api/v1/me/transactions", headers=headers(other)).json()["total"] == 0
    assert client.delete(f'/api/v1/me/devices/{second_device["device_id"]}', headers=headers(token)).status_code == 404
    assert second["participant_id"] not in client.get("/api/v1/me", headers=headers(token)).text
    assert accounting.reconcile().reconciled


def test_role_boundaries(auth_env):
    _, token = activate(auth_env)
    client, _, engine, admin = auth_env
    privileged = AuthService(engine, auth_env[1].settings)
    with privileged.sessions.begin() as session:
        gateway = Account(role="GATEWAY", status="active", login_name="test-gateway")
        session.add(gateway); session.flush()
        gateway_token = privileged.issue_session(session, gateway).session_token
    for raw in (token, gateway_token):
        assert client.get("/api/v1/admin/audit-events", headers=headers(raw)).status_code == 403
        assert client.post("/api/v1/admin/participants", headers=headers(raw), json={"name": "Test", "phone": "7654321098", "admin_confirmed_phone": True}).status_code == 403
    for raw in (admin, gateway_token):
        assert client.get("/api/v1/me", headers=headers(raw)).status_code == 403
        assert client.post("/api/v1/auth/login", headers=headers(raw), json={"phone": "9876543210", "password": PASSWORD}).status_code == 403
    for raw in (token, admin):
        assert client.get("/api/v1/gateway/status", headers=headers(raw)).status_code == 403
    assert client.get("/api/v1/gateway/status", headers=headers(gateway_token)).status_code == 200
    assert client.get("/api/v1/me").status_code == 401


def test_raw_secrets_absent_from_database_logs_and_read_responses(auth_env, caplog):
    caplog.set_level(logging.DEBUG)
    enrollment, token = activate(auth_env)
    device = approved_device(auth_env, token)
    client, _, engine, admin = auth_env
    with engine.connect() as connection:
        dump = "".join(str(connection.execute(text(f"SELECT row_to_json(t) FROM {table} t")).all()) for table in TABLES)
        stored_hashes = list(connection.scalars(select(Account.password_hash).where(Account.password_hash.is_not(None))))
        stored_hashes += list(connection.scalars(select(AuthSession.token_hash)))
    audit_response = client.get("/api/v1/admin/audit-events", headers=headers(admin))
    reads = audit_response.text + client.get("/api/v1/me/devices", headers=headers(token)).text
    for secret in (PASSWORD, token, admin, enrollment["enrollment_token"], device["device_secret"]):
        assert secret not in dump
        assert secret not in caplog.text
        assert secret not in reads
    assert all(field not in reads for field in ("password_hash", "token_hash", "encrypted_secret", "master_key"))
    assert all(value not in reads + caplog.text for value in stored_hashes)
    assert audit_response.headers["cache-control"] == "no-store"
    kinds = {e["kind"] for e in audit_response.json()["items"]}
    assert {"participant.enrolled", "participant.activated", "device.registered", "device.approved"} <= kinds
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(text("DELETE FROM audit_events"))


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=1000001", "limit=oops"])
def test_pagination_validation(auth_env, query):
    client, _, _, admin = auth_env
    assert client.get("/api/v1/admin/audit-events?" + query, headers=headers(admin)).status_code == 422


def test_validation_no_secrets_duplicate_phone_and_audit_pagination(auth_env):
    client, _, _, admin = auth_env
    enrollment = enroll(auth_env)
    response = client.post("/api/v1/admin/participants", headers=headers(admin), json={"name": "Test", "phone": "+919876543210", "admin_confirmed_phone": True})
    assert response.status_code == 409
    for body in ({"name": "Test", "phone": "9876543210", "admin_confirmed_phone": False},
                 {"name": "Test", "phone": "123", "admin_confirmed_phone": True},
                 {"name": "Test", "phone": "9876543210", "admin_confirmed_phone": "true"}):
        assert client.post("/api/v1/admin/participants", headers=headers(admin), json=body).status_code == 422
    secret = "sensitive-invalid-input"
    invalid = client.post("/api/v1/auth/login", json={"phone": "9876543210", "password": {"secret": secret}})
    assert invalid.status_code == 422 and secret not in invalid.text
    first = client.get("/api/v1/admin/audit-events?limit=1", headers=headers(admin)).json()
    second = client.get("/api/v1/admin/audit-events?limit=1&offset=1", headers=headers(admin)).json()
    assert first["total"] == second["total"] and first["total"] >= 3
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert client.post("/api/v1/register", json={}).status_code == 404


def test_runtime_privileges_and_no_role_escalation(auth_env):
    auth = auth_env[1]
    with auth.sessions() as session:
        assert session.scalar(text("SELECT current_user")) == "wallet_runtime"
        assert not session.scalar(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user"))
        assert not session.scalar(text("SELECT pg_has_role(current_user, 'wallet_migrator', 'MEMBER')"))
        assert not session.scalar(text("SELECT datdba = (SELECT oid FROM pg_roles WHERE rolname=current_user) FROM pg_database WHERE datname=current_database()"))
    for statement in ("UPDATE alembic_version SET version_num='tampered'", "DROP TABLE ledger_entries",
                      "UPDATE wallets SET balance_paise=100", "DELETE FROM accounts", "ALTER TABLE accounts ADD COLUMN bad int",
                      "UPDATE accounts SET role='ADMIN'", "INSERT INTO accounts (id,role,status,login_name) VALUES (gen_random_uuid(),'GATEWAY','active','bad')"):
        with pytest.raises(DBAPIError), auth.sessions.begin() as session:
            session.execute(text(statement))


def test_bootstrap_refuses_second_admin_and_weak_password(auth_env):
    with pytest.raises(ValueError, match="already exists"):
        create_first_admin(auth_env[2], "second-admin", PASSWORD)
    with pytest.raises(ValueError, match="Password"):
        create_first_admin(auth_env[2], "second-admin", "weak")


def test_concurrent_device_replacements_serialize(auth_env):
    _, token = activate(auth_env)
    first = approved_device(auth_env, token)
    auth = auth_env[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda label: auth.register_device(token, label), ("Replacement A", "Replacement B")))
    with Session(auth_env[2]) as session:
        devices = session.scalars(select(Device).order_by(Device.secret_version)).all()
        assert [d.status for d in devices] == ["revoked", "revoked", "pending"]
        assert [d.secret_version for d in devices] == [1, 2, 3]
    newest = max(results, key=lambda d: d.secret_version)
    auth.device_action(auth_env[3], newest.device_id, admin=True, approve=True)
    assert auth.authenticate_device(newest.device_id, newest.device_secret)
    with pytest.raises(AuthError):
        auth.authenticate_device(UUID(first["device_id"]), first["device_secret"])


def test_ip_limit_and_window_recovery(auth_env):
    from app.auth_models import AuthRateBucket
    auth = AuthService(auth_env[2], auth_env[1].settings.model_copy(update={"login_ip_limit": 2}))
    for phone in ("9876543210", "8765432109"):
        with pytest.raises(AuthError) as error:
            auth.login(phone, PASSWORD, "shared-ip")
        assert error.value.status == 401
    with pytest.raises(AuthError) as error:
        auth.login("7654321098", PASSWORD, "shared-ip")
    assert error.value.status == 429
    with auth_env[2].begin() as connection:
        connection.execute(update(AuthRateBucket).values(window_started_at=now()-timedelta(hours=1)))
    with pytest.raises(AuthError) as error:
        auth.login("7654321098", PASSWORD, "shared-ip")
    assert error.value.status == 401


def test_migration_from_populated_sprint_one(accounting_engine, settings):
    with accounting_engine.begin() as connection:
        command.downgrade(migration_config(connection), "0002_accounting")
    service = AccountingService(accounting_engine, settings)
    result = service.create_participant_and_wallet(external_reference="upgrade-only", display_name="Synthetic",
        idempotency_key="upgrade-only", actor_reference="test-admin")
    fund(service, result.wallet_id, 1500)
    with accounting_engine.begin() as connection:
        command.upgrade(migration_config(connection), "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_authentication"
        assert connection.scalar(text("SELECT count(*) FROM accounts")) == 0
    assert service.reconcile().reconciled
    with Session(accounting_engine) as session:
        assert session.get(Wallet, UUID(result.wallet_id)).balance_paise == 1500
    with pytest.raises(DBAPIError), accounting_engine.begin() as connection:
        connection.execute(text("UPDATE ledger_entries SET balance_delta_paise=0"))
