# Architecture

## Purpose and trust

This is a small, noncommercial college research prototype, not a production-ready
or regulatory-approved wallet. Users add small funds through their normal UPI apps
to the project owner's designated pool account. The project does not collect bank
or UPI credentials. An administrator will manually credit independently verified
deposits; screenshots, SMS notifications, or user claims alone cannot credit money.

Wallet-to-wallet transfers will move value only inside the PostgreSQL ledger.
They will not initiate bank or UPI transfers. The backend ledger must be authoritative
for balances and outcomes. A submitted, sent, delivered, queued, or locally cached
request is not proof of success. Only backend confirmation can establish success.

## Components

| Component | Current implementation | Later responsibility |
| --- | --- | --- |
| User app (`app/`) | Kotlin/XML fragments; ViewBinding/ViewModel; auth/device/read API repositories; Room timestamped read cache; Keystore credentials; optional system app lock | Request payments and display backend-confirmed outcomes |
| SMS gateway (`android/sms-gateway/`) | Separate Kotlin/XML app and application ID; inactive status screen | Receive/forward requests and relay confirmed outcomes |
| Backend (`backend/`) | FastAPI health/auth/device endpoints; internal accounting services, reconciliation, limits and audit | Controlled admin UI/payment interfaces |
| PostgreSQL | Eight accounting tables plus five auth tables; history guards; separate runtime/migration roles | External reconciliation workflow |
| Admin dashboard | Documented only, no routes/templates | Simple authenticated server-rendered verification pages |

The gateway is a separate Android application module in the existing root build.
Both applications share tool versions and Gradle wrapper. Kotlin support is built
into the existing Android Gradle plugin. Sprint 3 implements the requested light
cobalt/white participant screens in the existing app. Room version 2 preserves
`ui_preferences` and adds participant-scoped profile and confirmed wallet read
cache. It contains no credentials, ledger or seeded data. Exported schemas are
kept in `app/schemas/`; the backend remains the balance and outcome authority.

## Planned connectivity

```text
Existing UPI app --> owner's designated pool bank account
                             |
                    administrator verifies deposit
                             |
                 future authenticated admin pages
                             |
User app --cellular SMS--> Gateway --network--> FastAPI --> PostgreSQL ledger
User app <--confirmed reply-- Gateway <--result-- FastAPI
```

This diagram describes future behavior, not implemented payment or SMS paths.
User phones may have mobile data and Wi-Fi off but still require cellular SMS
service. The gateway needs cellular SMS reception and internet/backend connectivity.
The backend and database require connectivity. A gateway outage must leave requests
pending/unknown until backend outcomes can be obtained. Retry, authentication,
replay protection, idempotency, and reconciliation will be designed before real use.

## Backend foundation

The ASGI application creates its engine during lifespan startup and disposes it
on shutdown. SQLAlchemy uses the PostgreSQL psycopg driver, connection validation,
short connection/query timeouts, and hidden query parameters. `GET /health` checks
only process liveness. `GET /health/ready` runs a read-only `SELECT 1`, returns 503
for connection/query failures, and exposes no internal error details.

Alembic uses environment configuration without embedding a database URL in source
or its INI file. `0001_foundation` remains the empty baseline; `0002_accounting`
adds the accounting schema and triggers without seeding any participant or wallet.
Sprint 2 adds `0003_authentication` without changing accounting data or triggers.
Payment HTTP endpoints, SMS handling and funding integrations remain absent. The
gateway application remains inactive; Sprint 3 changes only participant UI/integration.

Limits default to wallet 10,000 paise (INR 100), payment 2,000 paise (INR 20), and
pool reserve 50,000 paise (INR 500). Environment overrides must be positive whole
integer paise and satisfy payment <= wallet <= pool. The accounting service enforces
these limits under transaction locks. Database monetary columns are `BIGINT`; Python
service inputs must be actual positive integers (booleans, floats and numeric strings
are rejected). Future Android amounts must be `Long`.

## Sprint 1 accounting

`backend/app/accounting.py` exposes `AccountingService(engine, settings)` to trusted
internal callers. Every mutation owns a fresh transaction and returns an immutable
result only after commit. No service is wired to an HTTP payment route or Android.

| Method | Effect |
| --- | --- |
| `create_participant_and_wallet` | One participant and one empty enabled wallet; no money entries |
| `credit_verified_funding` | Credit a deposit already verified against authoritative account records |
| `transfer` | Balanced debit/credit between distinct enabled wallets |
| `create_refund_hold` | Reserve available funds for a future external refund |
| `release_refund_hold` | Append an entry cancelling a hold; money remains in the wallet |
| `record_completed_refund` | Record an independently verified completed external refund and consume its hold |
| `reconcile` | Read-only consistent snapshot comparing balances, holds, transaction entries and net funding |

Participants use an opaque external reference, not an authentication credential.
Each participant has one wallet. Financial transactions are committed operations;
there is no persisted partially successful financial transaction status. Funding
records capture a unique external deposit reference, verifier reference and an
authoritative verification-record reference. Refund records retain the original
hold and link to exactly one release or completion transaction. Audit events and
idempotency records are append-only, alongside transactions and ledger entries.

Wallets store two integer projections: `balance_paise` (total participant funds)
and `held_paise` (reserved subset). Spendable balance is their difference. Ledger
entries store signed balance and held deltas:

| Operation | Balance deltas | Held deltas |
| --- | --- | --- |
| Funding | +amount to wallet | 0 |
| Transfer | -amount sender, +amount recipient | 0 on both |
| Refund hold | 0 | +amount |
| Refund release | 0 | -amount |
| Completed refund | -amount | -amount |

Only internal transfers are double-entry wallet movements. Funding and completed
refunds are explicitly recorded external inflow/outflow boundaries. The sum of
wallet ledger balances must equal verified funding minus completed refunds. This
is a participant-liability subledger, not a full bank/general ledger. The recorded
pool cap includes held funds; it does not attest to the actual bank balance or
account for incoming deposits that have not yet been verified and credited.

### Atomicity, locking and history

Lock order is: idempotency advisory lock; pool advisory lock for funding/refund
completion; existing refund row for release/completion; wallet rows ordered by UUID.
Transfers acquire both wallet rows with one ordered `SELECT ... FOR UPDATE` before
checking balance, enabled state and recipient capacity. All mutations use READ
COMMITTED isolation. Funding/refund completion share a transaction-scoped pool
lock, preventing concurrent credits from exceeding the recorded reserve cap.

The service checks locked wallet projections against ledger sums before changing
funds. Ledger INSERT triggers update the projections in the same transaction.
Wallet constraints prevent negative balance/holds or holds above total balance.
Deferred constraints check exact entry counts, wallets, signs and amounts at commit,
and validate funding/refund record links. A debit without its matching credit cannot
commit, including if a later insert, audit insert or commit-time check fails.

Database triggers reject UPDATE, DELETE and TRUNCATE on ledger entries, transaction
headers, funding records, audit events and idempotency records. Refunds can transition
only from held to released or completed; terminal records cannot change. Corrections
must append compensating operations. No general administrative correction/reversal
tool is exposed in this sprint. Reconciliation reports discrepancies without rewriting
history or silently adjusting balances. Migration downgrade is permitted only when
all accounting tables are empty; otherwise a forward migration is required.

### Retry semantics and trust boundaries

All mutations require a globally unique caller-generated idempotency key (1–128
characters). The stored SHA-256 fingerprint includes the operation, normalized
request details and actor/verifier reference. Identical retries return the original
committed result, even if wallet state or configured limits subsequently change.
Reusing a key with different valid details raises `IdempotencyConflict`. A separate
unique external-reference constraint prevents double-crediting the same deposit
with a different key. Concurrent retries serialize on the key's advisory lock.

Results, audit events and the financial operation commit together. Rejected or
rolled-back operations do not retain a key or a success audit event, so they can be
retried after the cause is resolved. Connection/lock timeouts and database failures
propagate to the caller; retry with the same key, since a lost commit acknowledgement
can leave the outcome unknown. There are no automatic service retries or key expiry.

Holds do not move money externally. A completed-refund call records an external
refund that has already been independently verified; it never initiates one. Release
and completion are permitted for an existing hold on a disabled wallet, so disabling
a wallet cannot prevent settling its existing obligation. New holds, funding and
transfers reject disabled wallets. Refund amounts may exceed the INR 20 transfer
limit but cannot exceed available funds.

Verification references are mandatory provenance, not automated bank verification.
An authenticated administrator workflow must independently verify evidence before
calling these methods. Screenshots, notifications and participant claims alone must
never be passed through as authorization. There is no public funding/refund API.
Sprint 2 implements authentication, operator authorization and least-privilege runtime
roles; external bank reconciliation remains future work. A database owner/superuser
can still bypass triggers and must remain outside the runtime trust boundary.

## Local operation and isolation

Compose exposes backend HTTP on loopback only, does not publish PostgreSQL, and
waits for database health before applying migrations and launching FastAPI. The
backend container runs as an unprivileged user. `.env` is ignored and excluded
from image builds. No real bank credentials, UPI credentials, API keys, or personal
secrets may be stored in source code, APK constants, or logs.

Health/configuration tests use a fake engine with independent settings. Accounting
tests use real PostgreSQL through a separate Docker test image. Every test receives
a random schema migrated through Alembic; concurrent workers use independent
connections. The runner uses a randomly named Compose project, fixed test-only
database name, random credentials, ephemeral port and separate volume, then removes
that project. `.env` is never loaded by test fixtures. Public-schema wallets and ledger
are asserted empty after the tests; all funded fixtures exist only in disposable test
schemas. Never point tests at the real demonstration database or seed funded wallets
there. The runtime Docker image excludes test code and development dependencies.

Reconciliation runs in a read-only REPEATABLE READ transaction to avoid comparing
different commit snapshots. It checks every wallet's balance/held projections,
active refund holds, exact per-transaction entries and pool net funding. It currently
scans the prototype dataset; larger deployments would need pagination/aggregation
and independent operational monitoring.

## Participant visual design

The Sprint 3 UI uses white/light-gray backgrounds, dark navy text, a rounded
cobalt-blue balance card, exactly three dots when the balance is concealed, and
tap-to-reveal behavior. Scan QR stays left and Enter UPI ID right. Bottom navigation
is Home, Add Money, Profile, with consistent typography/spacing and accessible
touch targets. Sprints 0-2 do not alter the current home-screen UI.

## Dependency references

Build wiring follows the official [KSP compatibility documentation](https://kotlinlang.org/docs/ksp-overview.html),
[Room release documentation](https://developer.android.com/jetpack/androidx/releases/room),
and [Lifecycle dependencies](https://developer.android.com/jetpack/androidx/releases/lifecycle).
Backend lifespan tests follow [FastAPI's testing guidance](https://fastapi.tiangolo.com/advanced/testing-events/).
Transaction boundaries and locks follow [SQLAlchemy transaction contexts](https://docs.sqlalchemy.org/en/21/orm/session_transaction.html)
and [PostgreSQL explicit locking](https://www.postgresql.org/docs/17/explicit-locking.html).
Commit-time ledger checks use [deferred constraint triggers](https://www.postgresql.org/docs/17/sql-createtrigger.html).

## Sprint 2 authentication and device authorization

`auth_models.py`, `security.py`, `auth_service.py`, `auth_schemas.py` and `api.py`
form a separate authentication layer around the unchanged financial engine.
Migration `0003_authentication` creates five empty tables:

| Table | Purpose |
| --- | --- |
| `accounts` | Role, pending/active/suspended status, normalized login, Argon2id password hash, participant link and manual phone-confirmation provenance |
| `enrollment_tokens` | Hash, expiry, redemption/revocation timestamps; no raw token |
| `auth_sessions` | Hash, account/device binding, expiry and revocation; no raw bearer |
| `devices` | Server UUID, participant, label, pending/active/revoked state, AES-GCM ciphertext, version, registration/approval/revocation/last-seen timestamps |
| `auth_rate_buckets` | Hashed target/IP keys and persistent fixed-window attempt counters |

Account role and identity constraints distinguish participants, administrators and gateways.
There is no public registration. Admin enrollment atomically calls the existing accounting
identity helper to create a participant and zero-balance wallet, creates the pending account,
stores a token hash and appends an audit event. It never creates a financial entry. Existing
Sprint 1 participants are not silently activated or assigned passwords during migration.

Phone numbers normalize to `+91[6-9][0-9]{9}`. The administrator must explicitly attest to manual
ownership confirmation, recorded as **admin-confirmed phone** with administrator ID and time.
Typed phone numbers do not prove ownership; automated OTP is absent. Account activation uses
a private, random 256-bit, expiring, single-use token. Reissue revokes outstanding tokens.
Redeem locks the account and rechecks the token after the lock so concurrent attempts cannot
activate twice. Default lifetime is 15 minutes.

Passwords use Argon2id (64 MiB memory, three iterations, one lane) with library-generated salts.
The minimum policy and bootstrap commands are in README. Sessions and enrollment tokens use
independent 256-bit randomness and domain-separated SHA-256 hashes. High-entropy opaque tokens
do not need password-style slow hashing. Tokens are returned only when issued, never read back.
Password login uses a dummy Argon2id verification for nonexistent accounts and generic failure
messages. PostgreSQL counters rate-limit per normalized login/token hash and direct client IP;
all attempts count and failed authentication does not roll back the counters. Windows reset on
the next attempt. No cleanup scheduler is implemented yet; prototype counters remain in storage.
Untrusted forwarded-IP headers are ignored; a future reverse proxy requires explicit trusted-IP
configuration before deployment. Rate limiting is not a general network DoS defense.

Every authenticated operation locks and checks the account, then rechecks session expiry and
revocation. Suspension revokes every session and disables its wallet. Reactivation permits new
login but never revives old credentials. Logout revokes one session; logout-all/password change
revoke every session, including the caller. Admin logout revokes all administrator sessions.
Session expiry defaults to one hour. Password recovery and MFA are not implemented.

### Roles, ownership and endpoints

All paths below are under `/api/v1`. There are no financial mutation endpoints.
Request models reject unexpected fields; validation errors omit input values. Responses are
explicit allowlisted models, never ORM serialization. Credential responses have `Cache-Control:
no-store`; all API responses disable caching. Request bodies, authorization headers, password
hashes, tokens and ciphertext are never emitted by application logging. Compose disables Uvicorn
access logging and proxy-header trust; external log collectors must also exclude credentials.

| Boundary | Endpoints |
| --- | --- |
| Public credential exchange | `POST /auth/redeem`, `POST /auth/login`, `POST /admin/login` (reject attached bearer credentials) |
| Participant session | `POST /auth/logout`, `/auth/logout-all`, `/auth/password`; `GET /me` |
| Approved participant device session | `GET /me/wallet`, `GET /me/transactions` |
| Participant device management | `POST /me/devices` registers/replaces; `GET /me/devices`; `DELETE /me/devices/{device_id}` |
| Administrator enrollment/status | `POST /admin/participants`; `GET /admin/participants/{participant_id}`; `PATCH /admin/participants/{participant_id}/status`; `POST`/`DELETE /admin/participants/{participant_id}/enrollment` reissue/revoke |
| Administrator devices | `GET /admin/participants/{participant_id}/devices`; `POST /admin/devices/{device_id}/approve`; `DELETE /admin/devices/{device_id}` |
| Administrator session/audit | `POST /admin/logout`, `/admin/password`; `GET /admin/audit-events` |
| Gateway only | `GET /gateway/status` role check; no message processing |

Participant reads derive ownership from the authenticated account, not a client-provided
participant ID. Other participants' devices return 404. History exposes only the caller's ledger
entries, not counterparties' private information. Wallet summary locks the wallet, compares ledger
sums to its projection, and returns 503 if reconciliation is needed. No local cache claims success.
History, device and audit lists accept `limit` 1-100 (default 20) and `offset` 0-1,000,000, return
`items/total/limit/offset`, and order consistently by creation time and UUID. Offset pagination can
shift between requests when new records arrive; this is acceptable for the small prototype.
Audit response details are allowlisted; financial verifier references are not exposed there.

Participant tokens cannot authorize administrator or gateway routes. Administrator/gateway tokens
cannot authorize participant routes. Gateway accounts/sessions are supported and tested through
internal isolated provisioning; no automatic gateway credential or public provisioning endpoint
exists. Gateway operational enrollment is deferred until its explicitly authorized sprint.

### Device lifecycle and secrets

A valid active participant session creates a pending device. It receives a unique random secret
once; the enrolling session is bound to that device. Administrator approval changes pending to
active. A PostgreSQL partial unique index permits only one active device per participant. Wallet
and history reads require a bound active device. Later password logins can bind an approved device
using its ID and secret together; password-only logins can manage profile/enrollment but cannot
read wallet information. The secret is not yet an SMS message signature or SMS protocol.

Replacement holds the participant account lock, revokes all previous non-revoked devices, revokes
their other bound sessions, inserts a new pending device with increasing secret version and binds
the current session. A lost response cannot retrieve the secret again: replace and approve again.
Revoked devices cannot authenticate even with their old secret; database triggers reject reviving
or changing revoked records and changing credential ownership/ciphertext/version in place.
Registration, replacement, approval and revocation append audit events in the same transaction.

Backend encryption uses AES-256-GCM, a random 12-byte nonce and associated data containing the
device UUID, participant UUID and version. Nonce and authenticated ciphertext/tag are stored;
raw device secrets and the master key are not. `DEVICE_MASTER_KEY` must be an environment-supplied
base64 encoding of 32 random bytes. Preserve it in secure operator storage outside source control.
Key loss requires revocation and re-enrollment; automated key rotation is not yet provided. The
application process can decrypt device secrets by design; database-at-rest protection does not
protect a compromised runtime/master key. Hashes are used for sessions/enrollment because those
only require equality checks, while future message authentication needs the device secret.

Authentication lock order is caller account, target participant account where relevant, then
wallet/device records. Participant paths lock only their own account. Accounting services still
use their existing ordered wallet locks and never acquire account locks, avoiding inverted lock
order. Rate-limit transactions commit independently and acquire IP then target buckets. No global
in-memory session state or rate counter is used.

### Android foundation

`data/auth/` contains response/credential models, a repository, an encrypted blob store and
Android Keystore/AtomicFile adapters. AES-GCM encrypts the complete credential bundle with a
non-exportable AndroidKeyStore key and local associated data. The file is under `noBackupFilesDir`;
app backup is disabled. Tampered/unreadable encrypted payloads fail closed and clear the blob.
No Room column, plaintext preference or APK constant stores a credential. Logout clears both
session and device credentials; same-participant login preserves its device, account switching
clears it. Replacement clears the old device secret before a request, then atomically saves a
confirmed enrollment response. Failed remote logout must still clear local credentials and must
not claim server revocation. Local logout also removes the one-time device secret, so a later login requires replacement
and administrator approval again. Sprint 3 adds the HTTP/UI integration described below.

Unit tests exercise authenticated encryption, serialization, tampering, clearing/replacement,
account isolation and redacted diagnostics with an injectable JVM cipher/blob.
Sprint 3 also adds isolated emulator UI and real
Android Keystore adapter tests. Physical hardware, rooted devices and backup/restore still
require separate verification. Release builds have no remote endpoint by default.

### Database role separation

Local Compose orders `db -> db-setup -> migrate -> backend`. The bootstrap owner provisions two
fixed local roles with distinct generated passwords; neither is superuser, CREATEDB or CREATEROLE.
`wallet_migrator` owns the public application schema and objects and runs migrations and the explicit first-admin CLI.
The web backend receives only `wallet_runtime` credentials. Runtime has SELECT for the required
read/auth tables, INSERT for participant/enrollment/auth/audit records, zero-default wallet INSERT,
and column-scoped UPDATE for account state/password, sessions, devices, counters and wallet enabled
state. It has no financial mutation grants, no DELETE/TRUNCATE/DDL, no migration-table access and
no role-promotion grant. A trigger also rejects runtime INSERT of ADMIN/GATEWAY accounts.

`app.db_roles` transfers ownership of known existing Sprint 1 objects only; it never rewrites rows.
`app.migrate` applies Alembic under migration credentials then grants runtime rights. Existing
append-only financial/audit triggers are unchanged. Application owners/superusers remain trusted
operators capable of bypassing protections. This setup is for the dedicated local prototype
cluster; do not apply it blindly to a shared database. Runtime credential compromise still grants
its application data permissions; this is not row-level security or an adversarial DBA boundary.
Test roles and credentials live in a separate disposable cluster/database and never use `.env`.

### Security references

Password hashing follows [argon2-cffi guidance](https://argon2-cffi.readthedocs.io/en/stable/howto.html).
Device encryption uses [cryptography AES-GCM](https://cryptography.io/en/latest/hazmat/primitives/aead/).
Android storage uses [Android Keystore](https://developer.android.com/privacy-and-security/keystore).
Role grants follow [PostgreSQL privileges](https://www.postgresql.org/docs/17/ddl-priv.html).


## Sprint 3 participant application

One `MainActivity` hosts XML/ViewBinding fragments driven by `MainViewModel` and the
pure `WalletController` state machine. Destinations are startup, activation, login,
device enrollment/approval, Home, Add Money, Profile, history and expired-session state.
The light cobalt/white/navy design shares colors, dimensions, typography, cards and
button styles. Forms and content scroll; raw password/token fields disable view-state
saving and are cleared on submission. Rotation retains nonsecret ViewModel state;
process restart reloads encrypted credentials and revalidates with the backend.

`HttpWalletApi` uses Sprint 2 schemas, opaque bearer sessions, ordinary TLS validation,
10-second connect and 15-second read/write timeouts, a 25-second call timeout, no
redirects, automatic connection retry, interceptors or credential/body logging. The
Gradle URL property configures one endpoint. Debug HTTP is restricted to emulator/
loopback hosts; release network configuration disallows cleartext. No payment or
funding mutation interface is introduced. Busy state prevents duplicate submissions.

Login can bind a stored device only for its cached matching participant phone.
Password-only recovery remains available. A pending device receives its one-time
secret into the existing Keystore/AtomicFile encrypted bundle and waits for manual
administrator approval. The enrolling session is already bound; approval refresh
loads the confirmed wallet. An unbound session with an approved stored device must
sign in again with that device. Lost responses require replacement and new approval;
raw secrets cannot be fetched. Revocation/expiry fails closed; expiration removes
only the session so a saved approved device can authenticate a later login. Confirmed
logout/revocation clears local credentials and cache. Offline logout clears locally
and explicitly reports that server revocation was not confirmed.

Room schema version 2 preserves the version-1 preferences table and adds a
participant-scoped profile/wallet cache with integer paise and a confirmation timestamp.
The database is a read cache, never an accounting ledger. Switching participants and
logout erase cached data; replacement removes cached wallet data before the request.
Only a successful server wallet response updates `Last confirmed`. Connectivity and
server outages retain a potentially valid session and display cached reads with an
honest warning. No transaction history is invented or persisted for offline use.
Expired/revoked sessions discard authenticated UI state. Generic backend errors cannot
reliably distinguish suspension from revocation; recovery directs users to sign in or
contact the administrator rather than guessing account status.

### Optional local privacy lock

`AppLock` persists only enabled/offered preferences. It starts locked on a cold launch
when enabled. AndroidX `BiometricPrompt` supports available biometrics and system
device credentials; no custom PIN/password, biometric data or authentication result is
stored. Successful activation/login offers setup or Not now; Profile can enable or
manage it later. Disable requires system authentication. A monotonic background timer
relocks after 30 seconds; Profile/Home can lock immediately. Every background or lock
transition hides the revealed balance. Rotation retains the policy state; a new
process always starts locked if enabled. Cancellation/unavailability leaves it locked.
A pending prompt's action intent may survive rotation, but no success result does.

The local lock does not create/renew a backend session and cannot authorize a payment.
Unlock revalidates the existing session when possible. Sensitive Activity contents use
`FLAG_SECURE`. If system authentication is unavailable, an explicitly confirmed clear-
local-data recovery action erases credentials/cache before disabling the local lock;
it never reveals cached information or claims server logout.

Home conceals the balance as exactly `•••` until tapped. Scan QR (left) and Enter UPI ID
(right) are visible disabled actions. Add Money honestly states that pool-account details
are unconfigured and does not invent an account, UPI identifier or funding confirmation.
