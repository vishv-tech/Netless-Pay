"""Explicit role boundaries; no financial mutation or SMS endpoints."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select

from app.auth_models import Device
from app.auth_schemas import (AdminLogin, AuditView, DeviceEnrollmentView, DeviceView, Enroll,
    EnrollmentView, Login, Page, PasswordChange, ProfileView, Redeem, RegisterDevice,
    SessionView, StatusChange, TransactionView, WalletView)
from app.auth_service import AuthError, AuthService, device_view
from app.models import AuditEvent, FinancialTransaction, LedgerEntry, Participant, Wallet

router = APIRouter(prefix="/api/v1")
bearer = HTTPBearer(auto_error=False)


def service(request: Request) -> AuthService:
    return request.app.state.auth


def token(value: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if value is None or value.scheme.lower() != "bearer" or len(value.credentials) > 128:
        raise AuthError(401, "Session unavailable")
    return value.credentials


Service = Annotated[AuthService, Depends(service)]
Token = Annotated[str, Depends(token)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1000000)]


def public_request(request):
    # Credentials from another role cannot be used as an implicit login authority.
    if request.headers.get("authorization"):
        raise AuthError(403, "Do not attach a session to this operation")
    return request.client.host if request.client else "unknown"


@router.post("/auth/login", response_model=SessionView)
def login(body: Login, request: Request, auth: Service):
    return auth.login(body.phone, body.password.get_secret_value(), public_request(request),
        device_id=body.device_id, device_secret=body.device_secret.get_secret_value() if body.device_secret else None)


@router.post("/auth/redeem", status_code=204)
def redeem(body: Redeem, request: Request, auth: Service):
    auth.redeem(body.enrollment_token.get_secret_value(), body.password.get_secret_value(), public_request(request))
    return Response(status_code=204)


@router.post("/auth/logout", status_code=204)
def logout(auth: Service, raw: Token):
    auth.logout(raw)
    return Response(status_code=204)


@router.post("/auth/logout-all", status_code=204)
def logout_all(auth: Service, raw: Token):
    auth.logout(raw, all_sessions=True)
    return Response(status_code=204)


@router.post("/auth/password", status_code=204)
def password(body: PasswordChange, auth: Service, raw: Token):
    auth.change_password(raw, body.current_password.get_secret_value(), body.new_password.get_secret_value())
    return Response(status_code=204)


def profile(session, account):
    participant = session.get(Participant, account.participant_id)
    return ProfileView(participant_id=participant.id, name=participant.display_name, phone=account.phone,
                       phone_confirmation=account.phone_confirmation, status=account.status)


@router.get("/me", response_model=ProfileView)
def me(auth: Service, raw: Token):
    with auth.authorized(raw, "PARTICIPANT") as (session, account, _):
        return profile(session, account)


@router.get("/me/wallet", response_model=WalletView)
def wallet(auth: Service, raw: Token):
    with auth.authorized(raw, "PARTICIPANT", approved_device=True) as (session, account, _):
        wallet = session.scalar(select(Wallet).where(Wallet.participant_id == account.participant_id).with_for_update())
        balance, held = session.execute(select(func.coalesce(func.sum(LedgerEntry.balance_delta_paise), 0),
            func.coalesce(func.sum(LedgerEntry.held_delta_paise), 0)).where(LedgerEntry.wallet_id == wallet.id)).one()
        if (balance, held) != (wallet.balance_paise, wallet.held_paise):
            raise AuthError(503, "Wallet requires reconciliation")
        return WalletView(wallet_id=wallet.id, balance_paise=balance, held_paise=held,
                          available_paise=balance-held, enabled=wallet.enabled)


@router.get("/me/transactions", response_model=Page[TransactionView])
def history(auth: Service, raw: Token, limit: Limit = 20, offset: Offset = 0):
    with auth.authorized(raw, "PARTICIPANT", approved_device=True) as (session, account, _):
        wallet = session.scalar(select(Wallet).where(Wallet.participant_id == account.participant_id).with_for_update())
        total = session.scalar(select(func.count()).select_from(LedgerEntry).where(LedgerEntry.wallet_id == wallet.id))
        rows = session.execute(select(FinancialTransaction, LedgerEntry).join(LedgerEntry,
            LedgerEntry.transaction_id == FinancialTransaction.id).where(LedgerEntry.wallet_id == wallet.id)
            .order_by(FinancialTransaction.created_at.desc(), FinancialTransaction.id.desc()).limit(limit).offset(offset))
        return Page(items=[TransactionView(transaction_id=t.id, kind=t.kind, amount_paise=t.amount_paise,
            balance_delta_paise=e.balance_delta_paise, held_delta_paise=e.held_delta_paise, created_at=t.created_at)
            for t, e in rows], total=total, limit=limit, offset=offset)


@router.post("/me/devices", response_model=DeviceEnrollmentView, status_code=201)
def register_device(body: RegisterDevice, auth: Service, raw: Token):
    return auth.register_device(raw, body.label)


@router.get("/me/devices", response_model=Page[DeviceView])
def devices(auth: Service, raw: Token, limit: Limit = 20, offset: Offset = 0):
    with auth.authorized(raw, "PARTICIPANT") as (session, account, _):
        return device_page(session, account.participant_id, limit, offset)


def device_page(session, participant_id, limit, offset):
    query = select(Device).where(Device.participant_id == participant_id)
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    items = session.scalars(query.order_by(Device.created_at.desc(), Device.id.desc()).limit(limit).offset(offset))
    return Page(items=[device_view(d) for d in items], total=total, limit=limit, offset=offset)


@router.delete("/me/devices/{device_id}", response_model=DeviceView)
def revoke_device(device_id: UUID, auth: Service, raw: Token):
    return auth.device_action(raw, device_id)


@router.post("/admin/login", response_model=SessionView)
def admin_login(body: AdminLogin, request: Request, auth: Service):
    return auth.login(body.username, body.password.get_secret_value(), public_request(request), role="ADMIN")


@router.post("/admin/logout", status_code=204)
def admin_logout(auth: Service, raw: Token):
    auth.logout(raw, all_sessions=True, role="ADMIN")
    return Response(status_code=204)


@router.post("/admin/password", status_code=204)
def admin_password(body: PasswordChange, auth: Service, raw: Token):
    auth.change_password(raw, body.current_password.get_secret_value(), body.new_password.get_secret_value(), role="ADMIN")
    return Response(status_code=204)


@router.post("/admin/participants", response_model=EnrollmentView, status_code=201)
def enroll(body: Enroll, auth: Service, raw: Token):
    return auth.enroll(raw, body.name, body.phone)


@router.get("/admin/participants/{participant_id}", response_model=ProfileView)
def inspect_participant(participant_id: UUID, auth: Service, raw: Token):
    with auth.authorized(raw, "ADMIN") as (session, _, __):
        return profile(session, auth.participant_account(session, participant_id))


@router.patch("/admin/participants/{participant_id}/status", status_code=204)
def status(participant_id: UUID, body: StatusChange, auth: Service, raw: Token):
    auth.set_status(raw, participant_id, body.status)
    return Response(status_code=204)


@router.post("/admin/participants/{participant_id}/enrollment", response_model=EnrollmentView)
def reissue(participant_id: UUID, auth: Service, raw: Token):
    return auth.manage_enrollment(raw, participant_id, reissue=True)


@router.delete("/admin/participants/{participant_id}/enrollment", status_code=204)
def revoke_enrollment(participant_id: UUID, auth: Service, raw: Token):
    auth.manage_enrollment(raw, participant_id, reissue=False)
    return Response(status_code=204)


@router.get("/admin/participants/{participant_id}/devices", response_model=Page[DeviceView])
def admin_devices(participant_id: UUID, auth: Service, raw: Token, limit: Limit = 20, offset: Offset = 0):
    with auth.authorized(raw, "ADMIN") as (session, _, __):
        auth.participant_account(session, participant_id)
        return device_page(session, participant_id, limit, offset)


@router.delete("/admin/devices/{device_id}", response_model=DeviceView)
def admin_revoke(device_id: UUID, auth: Service, raw: Token):
    return auth.device_action(raw, device_id, admin=True)


@router.post("/admin/devices/{device_id}/approve", response_model=DeviceView)
def approve(device_id: UUID, auth: Service, raw: Token):
    return auth.device_action(raw, device_id, admin=True, approve=True)


@router.get("/admin/audit-events", response_model=Page[AuditView])
def audit_events(auth: Service, raw: Token, limit: Limit = 20, offset: Offset = 0):
    allowed = {"account_id", "participant_id", "device_id", "status", "previous_status", "role"}
    with auth.authorized(raw, "ADMIN") as (session, _, __):
        total = session.scalar(select(func.count()).select_from(AuditEvent))
        rows = session.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit).offset(offset))
        return Page(items=[AuditView(id=e.id, kind=e.kind, actor_reference=e.actor_reference, created_at=e.created_at,
            details={k: v for k, v in e.details.items() if k in allowed}) for e in rows], total=total, limit=limit, offset=offset)


@router.get("/gateway/status")
def gateway_status(auth: Service, raw: Token) -> dict[str, str]:
    with auth.authorized(raw, "GATEWAY"):
        return {"status": "authorized", "role": "GATEWAY"}
