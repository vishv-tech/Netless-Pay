"""Transaction-owning authentication services. No credential values are logged."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.accounting import AccountingService
from app.auth_models import Account, AuthRateBucket, AuthSession, Device, EnrollmentToken
from app.auth_schemas import DeviceEnrollmentView, DeviceView, EnrollmentView, SessionView
from app.database import build_session_factory
from app.models import AuditEvent, Wallet
from app.security import DeviceCipher, PASSWORDS, check_password_policy, normalize_phone, random_token, token_hash, verify_password


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def now():
    return datetime.now(timezone.utc)


def audit(session, kind, actor, **details):
    session.add(AuditEvent(kind=kind, actor_reference=str(actor), details=details))


def device_view(device):
    return DeviceView(device_id=device.id, participant_id=device.participant_id, label=device.label,
        status=device.status, registered_at=device.created_at, revoked_at=device.revoked_at,
        last_seen_at=device.last_seen_at, approved_at=device.approved_at, secret_version=device.secret_version)


class AuthService:
    def __init__(self, engine, settings):
        self.settings = settings
        self.sessions = build_session_factory(engine)
        if settings.device_master_key is None:
            raise ValueError("DEVICE_MASTER_KEY is required to enable authentication")
        self.cipher = DeviceCipher(settings.device_master_key.get_secret_value())

    def rate_limit(self, action, identifier, ip, target_limit, ip_limit):
        """Counters commit independently, including for rejected authentication attempts."""
        current = now()
        cutoff = current - timedelta(seconds=self.settings.auth_rate_window_seconds)
        blocked = False
        with self.sessions.begin() as session:
            for value, limit in ((f"ip:{ip}", ip_limit), (f"target:{identifier}", target_limit)):
                key = token_hash("rate", action + ":" + value)
                old = AuthRateBucket.window_started_at <= cutoff
                query = insert(AuthRateBucket).values(key_hash=key, window_started_at=current, attempts=1)
                query = query.on_conflict_do_update(index_elements=[AuthRateBucket.key_hash], set_={
                    "attempts": case((old, 1), else_=AuthRateBucket.attempts + 1),
                    "window_started_at": case((old, current), else_=AuthRateBucket.window_started_at),
                }).returning(AuthRateBucket.attempts)
                blocked |= session.scalar(query) > limit
        if blocked:
            raise AuthError(429, "Too many attempts; try again later")

    @staticmethod
    def policy(password):
        try:
            check_password_policy(password)
        except ValueError as error:
            raise AuthError(422, str(error)) from None

    def issue_session(self, session, account, device_id=None):
        raw = random_token()
        ttl = self.settings.gateway_session_ttl_seconds if account.role == "GATEWAY" else self.settings.session_ttl_seconds
        expires = now() + timedelta(seconds=ttl)
        session.add(AuthSession(account_id=account.id, token_hash=token_hash("session", raw),
                                expires_at=expires, device_id=device_id))
        return SessionView(session_token=raw, expires_at=expires, role=account.role, participant_id=account.participant_id)

    def login(self, login_name, password, ip, role="PARTICIPANT", device_id=None, device_secret=None):
        if role == "PARTICIPANT":
            try:
                login_name = normalize_phone(login_name)
            except ValueError:
                login_name = "invalid:" + login_name.strip()
        else:
            login_name = login_name.strip().lower()
        self.rate_limit("login:" + role, login_name, ip, self.settings.login_attempt_limit, self.settings.login_ip_limit)
        with self.sessions.begin() as session:
            account = session.scalar(select(Account).where(Account.login_name == login_name, Account.role == role).with_for_update())
            valid = verify_password(account.password_hash if account else None, password)
            if not valid or account.status != "active":
                raise AuthError(401, "Invalid login credentials")
            if device_id is not None:
                device = session.get(Device, device_id)
                if not self._device_valid(device, account, device_secret):
                    raise AuthError(401, "Invalid login credentials")
                device.last_seen_at = now()
            if PASSWORDS.check_needs_rehash(account.password_hash):
                account.password_hash = PASSWORDS.hash(password)
            result = self.issue_session(session, account, device_id)
            audit(session, "session.login", account.id, account_id=str(account.id))
        return result

    def _device_valid(self, device, account, secret):
        return (device is not None and device.status == "active" and device.participant_id == account.participant_id
                and self.cipher.matches(device.encrypted_secret, secret, device.id, device.participant_id, device.secret_version))

    @contextmanager
    def authorized(self, raw, role, approved_device=False):
        with self.sessions.begin() as session:
            credential = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash("session", raw)))
            if credential is None:
                raise AuthError(401, "Session unavailable")
            account = session.scalar(select(Account).where(Account.id == credential.account_id).with_for_update())
            session.refresh(credential)  # Recheck after obtaining account lock; logout/suspension share this lock.
            if credential.revoked_at is not None or credential.expires_at <= now() or account.status != "active":
                raise AuthError(401, "Session unavailable")
            if account.role != role:
                raise AuthError(403, "Not permitted")
            device = session.get(Device, credential.device_id) if credential.device_id else None
            if credential.device_id and (device is None or device.status == "revoked" or device.participant_id != account.participant_id):
                raise AuthError(401, "Session unavailable")
            if approved_device and (device is None or device.status != "active"):
                raise AuthError(403, "An administrator-approved device is required")
            if device and device.status == "active":
                device.last_seen_at = now()
            yield session, account, credential

    def enroll(self, token, name, phone):
        phone = normalize_phone(phone)
        try:
            with self.authorized(token, "ADMIN") as (session, admin, _):
                identity = AccountingService.create_identity_in_transaction(session, "enrollment:" + uuid4().hex, name)
                account = Account(role="PARTICIPANT", status="pending", login_name=phone, phone=phone,
                    participant_id=UUID(identity.participant_id), phone_confirmation="admin-confirmed phone",
                    phone_confirmed_by=admin.id, phone_confirmed_at=now())
                session.add(account)
                session.flush()
                result = self._new_enrollment(session, account)
                audit(session, "participant.enrolled", admin.id, participant_id=identity.participant_id, account_id=str(account.id))
            return result
        except IntegrityError:
            raise AuthError(409, "Participant could not be enrolled; check existing enrollment") from None

    def _new_enrollment(self, session, account):
        session.execute(update(EnrollmentToken).where(EnrollmentToken.account_id == account.id,
            EnrollmentToken.revoked_at.is_(None), EnrollmentToken.redeemed_at.is_(None)).values(revoked_at=now()))
        raw = random_token()
        expires = now() + timedelta(seconds=self.settings.enrollment_ttl_seconds)
        session.add(EnrollmentToken(account_id=account.id, token_hash=token_hash("enrollment", raw), expires_at=expires))
        return EnrollmentView(participant_id=account.participant_id, account_id=account.id,
                              enrollment_token=raw, expires_at=expires)

    def manage_enrollment(self, token, participant_id, reissue):
        with self.authorized(token, "ADMIN") as (session, admin, _):
            account = self.participant_account(session, participant_id)
            if account.status != "pending":
                raise AuthError(409, "Enrollment is not pending")
            result = None
            if reissue:
                result = self._new_enrollment(session, account)
            else:
                session.execute(update(EnrollmentToken).where(EnrollmentToken.account_id == account.id,
                    EnrollmentToken.revoked_at.is_(None)).values(revoked_at=now()))
            audit(session, "enrollment.reissued" if reissue else "enrollment.revoked", admin.id, account_id=str(account.id))
        return result

    def redeem(self, raw, password, ip):
        digest = token_hash("enrollment", raw)
        self.rate_limit("redeem", digest, ip, self.settings.redemption_attempt_limit, self.settings.redemption_ip_limit)
        self.policy(password)
        with self.sessions.begin() as session:
            enrollment = session.scalar(select(EnrollmentToken).where(EnrollmentToken.token_hash == digest))
            if enrollment is None:
                raise AuthError(400, "Enrollment unavailable")
            account = session.scalar(select(Account).where(Account.id == enrollment.account_id).with_for_update())
            session.refresh(enrollment)
            if (account.status != "pending" or enrollment.expires_at <= now() or
                    enrollment.redeemed_at is not None or enrollment.revoked_at is not None):
                raise AuthError(400, "Enrollment unavailable")
            account.password_hash = PASSWORDS.hash(password)
            account.password_changed_at = enrollment.redeemed_at = now()
            account.status = "active"
            audit(session, "participant.activated", account.id, account_id=str(account.id))

    def logout(self, raw, all_sessions=False, role="PARTICIPANT"):
        with self.authorized(raw, role) as (session, account, credential):
            if all_sessions:
                self._revoke_sessions(session, account.id)
            else:
                credential.revoked_at = now()
            audit(session, "session.logout_all" if all_sessions else "session.logout", account.id, account_id=str(account.id))

    @staticmethod
    def _revoke_sessions(session, account_id):
        session.execute(update(AuthSession).where(AuthSession.account_id == account_id,
                                                AuthSession.revoked_at.is_(None)).values(revoked_at=now()))

    def change_password(self, raw, old, new, role="PARTICIPANT"):
        with self.authorized(raw, role) as (session, account, _):
            # Rate-limit password verification too; otherwise a stolen session bypasses login throttling.
            self.rate_limit("password", str(account.id), str(account.id), self.settings.login_attempt_limit, self.settings.login_ip_limit)
            if not verify_password(account.password_hash, old):
                raise AuthError(401, "Invalid credentials")
            self.policy(new)
            if old == new:
                raise AuthError(422, "Choose a different password")
            account.password_hash, account.password_changed_at = PASSWORDS.hash(new), now()
            self._revoke_sessions(session, account.id)
            audit(session, "password.changed", account.id, account_id=str(account.id))

    @staticmethod
    def participant_account(session, participant_id):
        account = session.scalar(select(Account).where(Account.participant_id == participant_id,
                                  Account.role == "PARTICIPANT").with_for_update())
        if account is None:
            raise AuthError(404, "Participant not found")
        return account

    def set_status(self, token, participant_id, status):
        with self.authorized(token, "ADMIN") as (session, admin, _):
            account = self.participant_account(session, participant_id)
            if account.password_hash is None:
                raise AuthError(409, "Revoke a pending enrollment instead")
            previous, account.status = account.status, status
            if status == "suspended":
                self._revoke_sessions(session, account.id)
            wallet = session.scalar(select(Wallet).where(Wallet.participant_id == participant_id).with_for_update())
            wallet.enabled = status == "active"
            audit(session, "participant.status", admin.id, participant_id=str(participant_id),
                  previous_status=previous, status=status)

    def register_device(self, raw, label):
        with self.authorized(raw, "PARTICIPANT") as (session, account, credential):
            old = session.scalars(select(Device).where(Device.participant_id == account.participant_id,
                                                       Device.status != "revoked").with_for_update()).all()
            version = int(session.scalar(select(func.coalesce(func.max(Device.secret_version), 0))
                                          .where(Device.participant_id == account.participant_id))) + 1
            device_id, secret = uuid4(), random_token()
            for device in old:
                self._revoke_device(session, device, account.id, except_session=credential.id)
            session.flush()
            device = Device(id=device_id, participant_id=account.participant_id, label=label, status="pending",
                secret_version=version, encrypted_secret=self.cipher.encrypt(secret, device_id, account.participant_id, version))
            session.add(device)
            session.flush()
            credential.device_id = device.id
            audit(session, "device.replaced" if old else "device.registered", account.id,
                  participant_id=str(account.participant_id), device_id=str(device.id))
            result = DeviceEnrollmentView(**device_view(device).model_dump(), device_secret=secret)
        return result

    @staticmethod
    def _revoke_device(session, device, actor, except_session=None):
        if device.status == "revoked":
            return
        device.status, device.revoked_at = "revoked", now()
        query = update(AuthSession).where(AuthSession.device_id == device.id, AuthSession.revoked_at.is_(None))
        if except_session:
            query = query.where(AuthSession.id != except_session)
        session.execute(query.values(revoked_at=now()))
        audit(session, "device.revoked", actor, participant_id=str(device.participant_id), device_id=str(device.id))

    def device_action(self, raw, device_id, admin=False, approve=False):
        with self.authorized(raw, "ADMIN" if admin else "PARTICIPANT") as (session, caller, _):
            device = session.get(Device, device_id)
            if device is None or (not admin and device.participant_id != caller.participant_id):
                raise AuthError(404, "Device not found")
            owner = self.participant_account(session, device.participant_id)
            session.refresh(device)
            if approve:
                if owner.status != "active" or device.status != "pending":
                    raise AuthError(409, "Device is not awaiting approval for an active participant")
                device.status, device.approved_at, device.approved_by = "active", now(), caller.id
                audit(session, "device.approved", caller.id, participant_id=str(device.participant_id), device_id=str(device.id))
            else:
                self._revoke_device(session, device, caller.id)
            session.flush()
            result = device_view(device)
        return result

    def authenticate_device(self, device_id, secret):
        """Internal future-channel verifier; no SMS protocol or public endpoint."""
        with self.sessions.begin() as session:
            device = session.get(Device, device_id)
            if device is None:
                raise AuthError(401, "Device unavailable")
            account = self.participant_account(session, device.participant_id)
            session.refresh(device)
            if account.status != "active" or not self._device_valid(device, account, secret):
                raise AuthError(401, "Device unavailable")
            device.last_seen_at = now()
            return device.participant_id
