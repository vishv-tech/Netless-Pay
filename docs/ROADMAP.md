# Roadmap

Implement only the sprint explicitly requested. Later entries are proposed scope,
not authorization to implement them.

| Sprint | Scope | Status |
| --- | --- | --- |
| 0 | Reuse Android app; gateway scaffold; FastAPI/PostgreSQL/Alembic; Compose; limits; documentation | Complete: both APKs/lint, existing Android unit test, 18 backend tests, and isolated PostgreSQL health/recovery checks passed |
| 1 | Backend accounting schema, atomic transfers, funding records, refund holds/completions, idempotency and reconciliation | Complete: 69 backend tests passed, migrations verified on isolated PostgreSQL, health/recovery checks passed |
| 2 | Controlled enrollment, participant/admin/gateway authorization, device approval, encrypted secrets, Android secure storage, database roles | Complete: 113 backend tests, migration/role/health checks, 9 Android unit tests, debug build; lint 0 errors/8 warnings |
| 3 | Kotlin/XML participant screens, Sprint 2 authentication/device/read APIs, timestamped Room cache, optional system app lock | Complete and accepted for now: 113 backend tests, 64 Android unit tests, both debug APKs; lint 0 errors/21 warnings. UI instrumentation deferred because isolated API 37 emulator stayed offline in adb |
| 4 | SMS protocol, replay protection, gateway authentication, forwarding/retries and confirmed replies | Planned |
| 5 | Explicitly scoped QR/identifier flows, operator funding tools and further recovery validation | Planned; scope requires authorization |
| 6 | Controlled small-value demonstration and reconciliation review | Planned |

## Sprint 0 history

No payments, authentication, SMS sending/receiving, real funding, seeded wallets,
or home-screen UI redesign. Gateway is inactive. Limits are configured and validated,
but transaction enforcement will be added with ledger operations. Room is limited
to local UI preferences and must never become the balance authority.

## Sprint 1 boundaries

Backend service layer only. No public payment endpoints or Android, bank, UPI, QR
or SMS integration. Migrations create empty tables; no real funding or funded demo
wallets are introduced. Funding/refund methods record already verified external
events under a trusted internal caller contract. Authentication and operator
authorization are deferred. The earlier proposed Sprint 1 authentication scope is
superseded by the user's explicit accounting-only sprint request.

## Rules carried forward

- Integer paise only; default maximums are INR 100 per wallet, INR 20 per payment,
  and INR 500 total pool reserve.
- Credit only administrator-verified deposits against authoritative bank records.
- Internal payments do not initiate bank or UPI transfers.
- Never show successful payment before backend confirmation.
- SMS requests require cellular service; gateway/backend need connectivity.
- Keep secrets out of source, APK constants, logs, and fixtures.
- Keep tests isolated and never seed funded demonstration wallets.
- Update this roadmap and HANDOFF.md after every sprint and report actual checks.
- This remains a small noncommercial college research prototype, not a
  production-ready or regulatory-approved product.

## Sprint 2 boundaries

No unrestricted registration, public transfer/funding/refund endpoints, real deposit
crediting, dashboard UI, final Android screens, QR/UPI integration or SMS processing.
Devices require administrator approval before wallet reads. Phone ownership is
manually recorded as **admin-confirmed phone**, not automated OTP verification.
Existing Sprint 1 accounting remains authoritative and has no public mutation route.

## Sprint 3 boundaries

Participant-only Android UI and read/auth/device networking. No administrator UI,
public payment/funding endpoints, bank/UPI integration, QR scanner, SMS processing,
or seeded funds. Device approval remains administrator-controlled through Sprint 2
APIs. Offline cache is explicitly last-confirmed data; server responses remain
necessary for authoritative account/device status and every future payment outcome.
Local app lock is optional privacy, separate from backend authentication.

## Sprint 4 work (not started)

Define a versioned SMS payment-request protocol authenticated using the enrolled,
approved device secret; enforce replay protection, expiry, sequence/nonce handling
and device revocation at the backend. Add separately authorized gateway provisioning,
SMS permission/transport, durable forwarding, retries and idempotency using the
existing atomic ledger services. Connect participant request/pending/failure/confirmed
status flows only after the backend confirms outcomes. Test duplicated, altered,
reordered and delayed messages, gateway outages and concurrent spends in isolation.
No bank/UPI transfer is implied. Real funding, operator dashboard and QR/UPI features
still require their own explicit sprint scope. Physical Keystore, biometric/device-
credential behavior across API levels, HTTPS and lost-device recovery need a later
real-device review before a demonstration.
