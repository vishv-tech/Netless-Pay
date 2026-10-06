# OfflineWallet

A small, noncommercial college research prototype of an SMS-requested wallet.
Sprint 3 connects the Kotlin/XML participant app to controlled enrollment, authentication,
approved devices and read-only wallet information, with an optional local app lock. This is not production-ready or regulatory-approved.

## Intended model and scope

- Participants use normal UPI in their existing apps to add small funds to the project
  owner's designated pool bank account. The prototype collects no bank or UPI credentials.
- An administrator manually credits deposits only after verification against authoritative
  bank records. Screenshots, SMS notifications and user claims alone never authorize credit.
- Wallet-to-wallet payments are internal ledger transfers only; they initiate no bank or UPI transfer.
- Future user payment requests can travel over SMS with mobile data and Wi-Fi off.
  Cellular SMS service is still required. The gateway phone and backend require connectivity.
- The backend ledger is the balance and outcome authority. Never display payment success
  before backend confirmation.
- There are no public payment, funding-credit, refund, QR, UPI or SMS endpoints. The
  participant screens are implemented; payment actions remain unavailable. Administrator
  dashboard UI and real funding remain future work. No real funds are seeded.

## Layout

```text
app/                   Existing Kotlin/XML user app; ViewBinding, ViewModel, Room
android/sms-gateway/   Separate inactive gateway Android module
backend/               FastAPI, SQLAlchemy, Alembic, PostgreSQL services and tests
compose.yaml           Local database, role setup, migration job and runtime backend
docs/                  Architecture, roadmap and sprint handoff
```

Both Android modules share the existing Gradle wrapper. The user app remains in place.
Room stores UI preferences and participant-scoped, timestamped confirmed-read cache data;
it is never the balance authority and stores no credentials. ViewModels and repositories
keep HTTP, cache and secure-storage work outside Activities and Fragments.

See [Android local-backend setup](docs/ANDROID_SETUP.md) for emulator URL configuration,
activation, device approval, optional app lock and repeatable verification commands.

## Local setup (PowerShell, project root)

Requires Docker Desktop's Linux engine. All generated credentials are for local development
only. The initializer preserves an existing device master key. For an existing Sprint 0/1
`.env`, it preserves the original database owner credentials as bootstrap credentials and
creates separate migration/runtime passwords. It never prints secrets.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\init-local.ps1
docker compose --env-file backend/.env up --build -d --wait
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

Compose provisions roles, applies migrations through `0003_authentication`, grants runtime
permissions, then starts FastAPI. Migrations seed no accounts or wallets. Preserve existing
volumes; do not delete a volume to upgrade or repair a password. Stop with
`docker compose --env-file backend/.env down` (without `--volumes`).

HTTP binds only to `127.0.0.1:8000`; PostgreSQL has no host port. `/health` checks liveness;
`/health/ready` checks database connectivity (200 ready, 503 unavailable). API schemas are at
`http://127.0.0.1:8000/docs`. Local HTTP is for loopback development only; any future remote
credential exchange requires HTTPS. Do not capture credential requests/responses in logs.

## Create the first administrator

After local setup, run an interactive one-off container using the migration role:

```powershell
docker compose --env-file backend/.env run --rm --no-deps migrate python -m app.bootstrap create-admin
```

The command prompts for username and password twice with echo disabled; it refuses a
terminal without hidden input. Passwords cannot be supplied as command-line arguments.
Minimum policy: 12-128 characters, at least one letter and one non-space digit/symbol;
reject common patterns `password`, `qwerty`, `letmein`, `123456`, `offlinewallet`.
Use a unique passphrase. Only the first administrator can be bootstrapped. Nothing creates
an administrator at application startup. No password hash or session token is printed.

Sign in with `POST /api/v1/admin/login` using `username` and `password`. The opaque bearer
token is returned once in the response; subsequent requests use `Authorization: Bearer ...`.
Do not place tokens in URLs, shell history, screenshots or shared API-console recordings.

## Enrollment, sessions and devices

1. Administrator manually confirms phone ownership, then calls `POST /api/v1/admin/participants`
   with `name`, `phone` and `admin_confirmed_phone: true`. Accepted Indian mobile formats are
   ten digits, `91` prefix or `+91` prefix, with spaces/parentheses/hyphens. Storage is `+91` plus ten digits.
2. The backend atomically creates a pending account and empty wallet, returning one random
   enrollment token (15-minute default expiry). Only its SHA-256 hash is stored. Deliver it
   privately; a lost token must be reissued. There is no public registration endpoint.
3. Participant calls `POST /api/v1/auth/redeem` with `enrollment_token` and `password`. Redemption
   activates the account once. Expired, revoked, reused or altered tokens fail.
4. `POST /api/v1/auth/login` takes `phone` and `password`. Argon2id verifies the password and
   a random opaque session is returned (one-hour default). PostgreSQL stores only a token hash.
   Login failures are generic. PostgreSQL rate counters apply across backend workers/restarts.
5. A password-only session can manage its own profile and device enrollment. Register/replace
   with `POST /api/v1/me/devices`, body `label`. The response contains a pending device and its
   secret once. The old active/pending device is revoked immediately on replacement.
6. Administrator approves it with `POST /api/v1/admin/devices/{device_id}/approve` after checking
   participant/device identity. Only sessions bound to an active approved device can read
   wallet summary/history. The enrolling session is bound automatically. Later logins supply
   both `device_id` and `device_secret` to bind a new session.
7. Device lists never return secrets. Revocation invalidates bound sessions. A lost enrollment
   response requires replacement and approval again. Logout revokes the current session;
   logout-all and password change revoke all sessions, including the caller's session.
   Suspension revokes sessions and disables the wallet; reactivation never restores old sessions.

Phone status is explicitly **admin-confirmed phone**. A typed number does not prove ownership.
There is no automated OTP flow. Password recovery, MFA and automated gateway provisioning are
not implemented. Gateway authorization is reserved and tested; `/api/v1/gateway/status` is only
a role check, with no SMS behavior or access to participant/admin operations.

| Capability | PARTICIPANT | ADMIN | GATEWAY |
| --- | --- | --- | --- |
| Own profile/session/device management | Yes | No | No |
| Own confirmed wallet/history | Approved bound device required | No | No |
| Enroll, suspend/reactivate, inspect participants | No | Yes | No |
| Inspect/approve/revoke participant devices; inspect audit | No | Yes | No |
| Gateway status | No | No | Yes |
| Public transfer/funding/SMS processing | Absent | Absent | Absent |

Full endpoint details and storage/locking design: [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Configuration and secret storage

`backend/.env.example` has empty secret placeholders. Use the initializer or generate distinct
random local credentials yourself. Never put real bank credentials, UPI credentials, API keys,
passwords, tokens or encryption keys in source code, APK constants or logs. `.env`, local SDK
paths, signing keys and build output are ignored and excluded from Docker build context.
Avoid `docker compose config` without `--quiet`: expanded output contains secrets.

| Variable | Default / purpose |
| --- | --- |
| `MAX_WALLET_BALANCE_PAISE` | 10000 (INR 100) |
| `MAX_PAYMENT_PAISE` | 2000 (INR 20) |
| `MAX_POOL_RESERVE_PAISE` | 50000 (INR 500) |
| `DB_HOST`, `DB_PORT`, `DB_NAME` | localhost, 5432, offlinewallet; Compose uses host db |
| `DB_USER`, `DB_PASSWORD` | wallet_runtime, required random local password |
| `DB_ADMIN_USER`, `DB_ADMIN_PASSWORD` | Local bootstrap/database owner only |
| `MIGRATION_DB_PASSWORD` | Separate wallet_migrator password |
| `DEVICE_MASTER_KEY` | Required base64-encoded 32 random bytes, AES-256-GCM key |
| `ENROLLMENT_TTL_SECONDS`, `SESSION_TTL_SECONDS` | 900, 3600 |
| `GATEWAY_SESSION_TTL_SECONDS` | 86400 for internally provisioned gateway sessions |
| `AUTH_RATE_WINDOW_SECONDS` | 900 |
| `LOGIN_ATTEMPT_LIMIT`, `LOGIN_IP_LIMIT` | 5 per target, 30 per direct client IP/window |
| `REDEMPTION_ATTEMPT_LIMIT`, `REDEMPTION_IP_LIMIT` | 5 per token hash, 20 per direct client IP/window |
| `BACKEND_PORT` | 8000 (loopback only) |

All monetary storage remains integer paise. Rate limiting counts successful and failed attempts;
forwarded-IP headers are not trusted. Password checks during password change are also throttled.

Device secrets are independently random 256-bit values. The server encrypts them with AES-GCM,
a fresh nonce and device/participant/version-associated data. The master key is supplied only
through environment configuration, never a database column. Preserve it securely: losing it
requires revoking/re-enrolling devices. Automated key rotation is not implemented.

Android uses a generated non-exportable Android Keystore key with AES-GCM and an atomic encrypted
file in `noBackupFilesDir`. Backup is disabled. Logout clears local session and device credentials;
replacement clears old device credentials before a request and saves the new response atomically.
Because local logout also clears the device secret, the next login needs device replacement
and approval again. Diagnostic model strings are redacted. `BuildConfig.BACKEND_BASE_URL`
is configured using `WALLET_API_BASE_URL`; debug defaults to the safe emulator address
`http://10.0.2.2:8000/`, while an unconfigured release uses an empty placeholder.
No password, token or encryption key is embedded in Kotlin or Gradle.

## Database responsibilities

The local bootstrap owner is used only by `db-setup`; `wallet_migrator` owns the public application schema and its
objects and runs Alembic/bootstrap. The backend receives only `wallet_runtime` credentials.
Runtime has explicit reads and limited auth/enrollment writes, no financial writes, no role
promotion, no DDL/database-drop privileges, and no access to `alembic_version`. Append-only
ledger/audit triggers remain intact. Existing known Sprint 1 objects transfer to the migration
role without altering their data. Direct Python development must separately provision these
roles; run `python -m app.migrate` with migration environment and `uvicorn app.main:app --no-access-log
--no-proxy-headers` with runtime environment. Never run the web process with migration credentials.

## Repeat verification

From the project root, with Docker Desktop running:

```powershell
python backend/scripts/check_compose.py
python backend/scripts/check_local_config.py
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --max-workers=2
# Only with a booted emulator/device; repositories use isolated synthetic test data:
.\gradlew.bat :app:connectedDebugAndroidTest --max-workers=2
```

The Docker command runs **all backend tests**, migration/model checks, populated Sprint 1 upgrade,
accounting concurrency/reconciliation, runtime authorization tests and live health outage/recovery.
It creates a random test project, a separate `offlinewallet_test` database/volume, random secrets
and random per-test schemas. It never loads the demonstration `.env`. Funding fixtures stay in
those disposable schemas. It asserts public wallets/ledger remain empty, then removes only its
own containers/volume. Plain local pytest intentionally skips PostgreSQL tests without isolated
runner configuration; it does not substitute SQLite.

Optional local preflight:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
Push-Location backend
.\.venv\Scripts\python.exe -m pytest -m 'not postgres' -p no:cacheprovider
Pop-Location
```

APK: `app/build/outputs/apk/debug/app-debug.apk`. Reports: `app/build/reports/tests/testDebugUnitTest/`
and `app/build/reports/lint-results-debug.html`. JVM credential tests do not prove physical
Android Keystore behavior. No physical-device/SMS verification is claimed.

See [ROADMAP.md](docs/ROADMAP.md) and [HANDOFF.md](docs/HANDOFF.md) for actual results and remaining work.
