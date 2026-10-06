# Sprint 2 handoff

Date: 2026-10-06. Scope: participant authentication, administrator authorization,
secure device enrollment and Android credential-storage foundation. Sprint 3 is not started.

## Starting state and preserved work

The interrupted run had already added authentication models, cryptographic utilities,
authentication configuration, dependency pins, Alembic model loading and the shared
accounting participant/wallet identity helper. Those edits were inspected and retained.
The continuation completed missing services, API, migrations, role setup, bootstrap,
Android storage, tests and documentation; it did not restart the project or replace the app.

`git status` and `git diff` were attempted: this directory has no `.git` repository, so
Git-based change comparison was unavailable. No AGENTS.md was found. No reset, checkout
or clean was used. Sprint 0/1 migration history and accounting safeguards remain intact.

## Created and changed files

- Retained/extended partial work: `backend/app/auth_models.py`, `security.py`, `config.py`,
  `accounting.py`, `backend/alembic/env.py`, `backend/requirements.txt`.
- New migration: `backend/alembic/versions/0003_authentication.py` (five auth tables,
  role/phone/status checks, indexes, one-active-device constraint, runtime role-insert
  guard, device history guard). No seeded accounts, devices or funds; no financial
  schema changes. Populated authentication downgrade refuses erasure.
- New backend modules: `app/auth_schemas.py`, `auth_service.py`, `api.py`, `bootstrap.py`,
  `db_roles.py`, `migrate.py`; updated `app/main.py` for routes, safe errors and no-cache responses.
- Deployment/configuration: `compose.yaml`, `backend/Dockerfile`, `backend/.env.example`,
  `backend/scripts/init-local.ps1`, `check_compose.py`, new `check_local_config.py`.
- Tests: new `backend/tests/test_auth.py`, `test_security.py`; updated `conftest.py`,
  `test_accounting.py` (new head expectation), `test_health.py` (auth allowed; financial routes absent).
- Android: new `app/src/main/java/com/example/offlinewallet/data/auth/` files
  `AuthModels.kt`, `CredentialStore.kt`, `AndroidCredentialStorage.kt`, `AuthRepository.kt`;
  new `app/src/test/java/com/example/offlinewallet/data/auth/CredentialStoreTest.kt`;
  updated `app/build.gradle.kts` (empty URL placeholder) and `AndroidManifest.xml` (disable backup).
- Updated `README.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, this handoff.

## Behavior and boundaries

Administrator enrollment atomically creates a pending participant and zero-balance wallet,
records **admin-confirmed phone** provenance and returns an expiring token once. Phone
normalization does not establish ownership; OTP is not implemented. Redemption sets an
Argon2id password and activates once. Reissue/revoke, expiration and concurrent redemption
are checked under account locks. There is no public registration.

Random session tokens are stored only as domain-separated hashes. Every authenticated
request checks role, ownership, active account, expiry/revocation and any bound device.
Login failures are generic and login/redemption counters persist in PostgreSQL. Password
change revokes all sessions; suspension revokes sessions and disables the wallet. Admin,
participant and gateway credentials cannot cross role boundaries.

Devices start pending and require administrator approval. Only approved device-bound
sessions read wallet/history. Replacement revokes older devices and other bound sessions,
returns a new secret once and requires approval again. Server secrets use AES-256-GCM
with nonce and identity/version-associated data; the master key is environment-only.
Read endpoints omit secrets/ciphertext/hashes. Security actions append to immutable audit.

The first-admin command uses hidden interactive input, refuses weak passwords and duplicate
bootstrap, accepts no password arguments, and is never called by startup. Separate local
migration/runtime roles restrict the runtime to required auth/enrollment reads/writes; it
cannot mutate financial history, promote roles, modify Alembic history or drop schema/database.

Android stores an encrypted credential bundle using Android Keystore and AtomicFile in
noBackupFilesDir, clears credentials on logout and old device secrets before replacement,
and redacts diagnostic model strings. There are no final screens or network calls. The
existing home layout SHA-256 remains
`4EDB8F1A46136317C0F7745EBE5157E785132339B16E228C2B4340DA66A1D9BE`.

## Verification

Final verification completed successfully. There are no remaining Sprint 2 build or test blockers.

- Final `python backend/scripts/check_compose.py`: **exit 0**, **113 passed**, **0 failed/skipped**,
  one upstream Starlette/HTTPX TestClient deprecation warning, **181.96 seconds** for pytest.
  This includes all 69 existing Sprint 0/1 tests, 33 PostgreSQL authentication tests and
  11 security unit tests. All accounting concurrency and reconciliation tests passed.
- PostgreSQL applied `0001_foundation -> 0002_accounting -> 0003_authentication`.
  Model/schema comparison, repeatable migration, empty downgrade/re-upgrade, populated
  Sprint 1 upgrade and financial history protections passed. Public application schema
  ownership is `wallet_migrator`; runtime has USAGE, no CREATE and no Alembic SELECT.
- Live health/readiness returned 200; stopping PostgreSQL produced readiness 503 while
  liveness stayed 200; restart restored readiness 200. Public wallets/ledger remained
  empty. The disposable test project's containers, network and volume were removed.

- First isolated full run: **100 passed**, one upstream Starlette/HTTPX deprecation warning;
  health 200, readiness 200 -> 503 while database stopped -> 200 after recovery; exit 0.
- Final local non-PostgreSQL preflight: **30 passed, 83 deselected**, one upstream warning.
- Android command: `./gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug --max-workers=2`:
  **BUILD SUCCESSFUL**, **9 unit tests, 0 failures/errors/skips**, debug APK built,
  **lint 0 errors, 8 warnings**. Eight tests cover new credential storage; one existing test remains.
- Lint warnings: existing target SDK 36, available AGP/Core/AppCompat/Room updates,
  and two unused color resources. Home-screen resources were not changed to silence warnings.
- Android verification initially encountered OneDrive access errors in generated test/lint
  output directories. Removing only those verified generated directories resolved them;
  source files were preserved. Gradle cache/SDK access required approved sandbox escalation.
- Isolated local initializer check: **exit 0**, fresh generation, output redaction, legacy
  owner/password preservation and stable repeat runs verified using synthetic files.
- Python compilation and documentation local-link validation passed.
- `pip check`: no broken requirements. New crypto dependencies installed successfully.
- No physical-device, Android Keystore hardware, emulator UI, SMS or bank verification was performed.
- The demonstration database and its `.env` were not migrated, funded, seeded or modified.

## Exact repeat and operator commands

From the workspace root:

```powershell
python backend/scripts/check_compose.py
python backend/scripts/check_local_config.py
$env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug --max-workers=2
```

The backend runner uses a random disposable Compose project and fixed test-only database;
all funded fixtures are isolated schemas. It verifies migration/model agreement, upgrade
from populated Sprint 1, runtime privileges, concurrency/reconciliation and health recovery.
It removes only its own test containers/network/volume. The initializer check uses synthetic
files under ignored build output, never the real `.env`.

When ready to upgrade the local demonstration stack explicitly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\init-local.ps1
docker compose --env-file backend/.env up --build -d --wait
docker compose --env-file backend/.env run --rm --no-deps migrate python -m app.bootstrap create-admin
```

Preserve the database volume and existing master key. The initializer preserves legacy
database owner/password values and generates separate runtime/migration credentials.
Existing Sprint 1 accounting participants remain untouched and are not auto-enrolled.

## Remaining limitations and Sprint 3

- This remains a small noncommercial college research prototype, not production-ready
  or regulatory-approved. Runtime credentials still access required application data;
  database owners/superusers can bypass triggers. No RLS or external security audit is claimed.
- Manual phone confirmation only; no OTP, MFA, self-service password recovery or automated
  gateway provisioning. Gateway role checks are present; its message protocol is not.
- Master-key rotation/backup procedures and physical Keystore/reinstallation behavior need
  operational validation. Lost device-secret responses require replacement and approval.
- Rate limits are fixed windows, count every attempt, and can temporarily lock out a target.
  Stale buckets are retained; cleanup/monitoring and trusted proxy configuration are future work.
- Loopback HTTP only. HTTPS and credential-safe operational logging must be set up before
  any remote-phone integration. Local clearing on failed logout cannot guarantee server revocation.
- No public payments/funding/refunds, real deposit crediting, final Android screens, admin
  dashboard, QR/UPI integration or SMS processing was added.
- Sprint 3 should implement only its next explicitly authorized UI/networking scope:
  enrollment/login/profile and device approval/replacement states, handling revoked/expired
  sessions and uncertain responses. Controlled admin workflows need authoritative verification;
  payment success must always wait for the backend. Define scope before implementation.

---

# Sprint 1 handoff (historical)

Date: 2026-10-06. Scope: backend wallet accounting and atomic transfer engine only.
The prior Sprint 0 handoff is retained below as historical context.

## Delivered in Sprint 1

- `backend/app/models.py`: participants, wallets, financial transactions, ledger
  entries, funding records, refund records, audit events and idempotency records.
- `0002_accounting`: empty schema migration with BIGINT paise, foreign keys,
  relevant indexes, unique external references, balance/hold checks, append-only
  history triggers, refund transition guards and deferred accounting constraints.
- `backend/app/accounting.py`: participant/wallet creation, verified-funding credit,
  atomic internal transfer, refund hold/release/completion, and reconciliation.
- Money operations use one database transaction, ordered wallet locks and committed
  idempotency results. Funding/refund completion serialize pool reserve changes.
  Wallet projections are maintained by ledger INSERT triggers. Transfer debit and
  credit cannot commit independently.
- Every mutation appends an audit event and idempotency result on success. Identical
  retries return the original result; changed valid request details are rejected.
  Failed operations roll back all changes, including audit and idempotency writes.
- A read-only snapshot reconciles wallet balance/held projections, active holds,
  per-transaction ledger entries, and verified funding minus completed refunds.
- Real PostgreSQL test fixtures use freshly migrated disposable schemas in a separate
  Docker test database. The existing runner now runs the whole backend suite before
  health outage/recovery checks, then removes its test containers/network/volume.
- README, architecture and roadmap now describe the implemented accounting engine
  and its trust boundaries. Android applications and home-screen files are unchanged.

## Sprint 1 verification

- `python backend/scripts/check_compose.py`: **exit 0**. Final full suite:
  **69 passed** (50 PostgreSQL accounting tests and 19 health/configuration tests),
  with one upstream Starlette/HTTPX TestClient deprecation warning.
- Real PostgreSQL applied `0001_foundation` then `0002_accounting`; final revision
  was `0002_accounting (head)`. Tests verified repeatable upgrades, model/schema
  agreement, empty-schema downgrade/re-upgrade, and refusal to downgrade populated
  accounting tables. Downgrade takes exclusive locks before checking for records.
- Tests cover successful balanced transfers, insufficient funds, self-transfer,
  non-integer/nonpositive amounts, disabled wallets, payment/recipient/pool limits,
  identical and changed-key retries, concurrent duplicate requests, competing spends,
  opposite-direction transfers, and concurrent credits at the pool cap.
- Failure injection observed the uncommitted debit before rejecting the credit;
  balances, ledger, transaction, audit and key state rolled back together. A retry
  with that key subsequently succeeded. A debit without a credit also failed the
  deferred commit-time database constraint.
- Refund holds/releases/completions, terminal-state rejection, funding verification
  metadata/deduplication, reconciliation and corrupted balance detection passed.
  UPDATE/DELETE/TRUNCATE attempts against immutable history were rejected. Funding
  and refund records could not reference the wrong transaction type.
- The API schema contains only `/health` and `/health/ready`; no payment, funding
  or refund endpoints are exposed.
- Live health checks returned 200 when ready, readiness returned 503 with PostgreSQL
  stopped while liveness remained 200, and readiness recovered to 200 after restart.
- The test database's public wallets and ledger stayed empty. All per-test schemas,
  temporary test containers, network and volume were removed successfully.
- Python compilation and `pip check` passed. The local preflight unit run passed
  18 tests with the upstream warning plus a pytest-cache permission warning; the
  final Docker run disables pytest's cache provider and had only the upstream warning.
- The Android home layout hash still equals the Sprint 0 hash recorded below.
  No Android source, build configuration or application integration was changed.

There are no remaining Sprint 1 test or migration blockers. The restricted shell
initially could not access Docker; approved escalation enabled the isolated checks.

## Scope and remaining limitations

- No public payment/funding/refund endpoints, authentication or operator authorization.
  No Android, bank, UPI, QR or SMS integration; no external money movement.
- Funding and completed-refund functions require verifier and authoritative-record
  references. These are trusted internal recording functions, not independent bank
  verification. Future authenticated admin workflows must verify records before calls;
  screenshots, notifications or participant claims alone never authorize credit.
- The recorded pool reserve measures net credited liabilities, including holds; it
  cannot prove the actual bank balance or account for uncredited incoming deposits.
- Database owner/superuser access can bypass triggers. Least-privilege runtime roles
  and operational administration remain future work. Failed operations are not written
  into the financial success audit; no separate rejected-request audit exists yet.
- Reconciliation reports discrepancies without repairing evidence. General correction
  or transfer-reversal tooling is deferred; any correction must use compensating
  entries. Refund releases already append compensating hold entries.
- Idempotency keys are global, retained indefinitely, and include actor provenance in
  their fingerprint. Retry uncertain outcomes with the same key. Database/lock failures
  propagate; the service does not automatically retry them.
- Reconciliation scans the small prototype dataset. No large-scale load, crash-recovery,
  device or external-rail tests were performed. Android was unchanged and not rebuilt.
- All migrations/funding fixtures were exercised only in disposable test environments.
  The demonstration database was not migrated, seeded, funded or otherwise modified.

## Commands and next sprint

From the project root, repeat the full isolated backend verification:

```powershell
python backend/scripts/check_compose.py
```

To build and apply the empty accounting schema to the normal local stack when ready:

```powershell
docker compose --env-file backend/.env up --build -d --wait
```

No seeded wallets are created. Preserve the existing database volume. A downgrade
that would erase accounting records is rejected; use forward migrations.

Proposed Sprint 2: participant/operator authentication and authorization, then a
controlled administrator deposit-verification workflow. Await the user's explicit
scope; do not connect payment channels as part of Sprint 1.

---

# Sprint 0 handoff (historical)

Date: 2026-10-06. Scope: project foundation only.

## Starting state

The root contained an existing Kotlin/XML Android app with a Hello World home
screen. No AGENTS.md was found in the workspace or its ancestor directories.
The directory was not a Git repository. The app was reused in place.

## Delivered

- Existing `app/`: ViewBinding, a MainViewModel, and Room UI-preference scaffolding
  with KSP/exported schema; existing home-screen resources preserved.
- Both modules compile against SDK 37 to satisfy the pre-existing AndroidX Core
  1.19.0 dependency; target SDK 36 and minimum SDK 26 are preserved.
- `android/sms-gateway/`: separate application ID, Kotlin/XML activity, ViewBinding,
  inactive status screen, and shared root Gradle tooling. No SMS/network permissions.
- `backend/`: FastAPI liveness/readiness, PostgreSQL environment settings,
  SQLAlchemy engine/session setup, Alembic empty foundation migration, pinned direct
  dependencies, secret-free `.env.example`, Dockerfile, and isolated unit tests.
- `compose.yaml`: local PostgreSQL and non-root backend, healthchecks, persistent
  database volume, loopback HTTP only, no PostgreSQL host port.
- Configurable positive integer paise limits: 10000 wallet, 2000 payment, 50000 pool.
- Local environment initializer and disposable Compose integration check.
- README, architecture, roadmap, handoff, and expanded secret/build-output ignore rules.

No authentication, payments, SMS handling, admin UI, funding, or wallet seeds were
implemented. No demonstration database has been funded. The backend ledger will
be authoritative in later sprints; Room is only a local UI-preference store.

## Verification

- Backend: `backend/.venv/Scripts/python.exe -m pytest` from `backend/`: **18 passed**.
  One upstream Starlette warning says its HTTPX-based TestClient integration is
  deprecated. This did not fail the tests.
- `backend/.venv/Scripts/python.exe -m pip check`: **no broken requirements**.
- `docker compose --env-file backend/.env config --quiet`: **passed**.
- `python backend/scripts/check_compose.py`: **passed against real PostgreSQL**.
  Both endpoints returned 200 when healthy; readiness returned 503 after stopping
  PostgreSQL while liveness remained 200; readiness returned 200 after recovery.
  Alembic reached `0001_foundation (head)`. The only public table was
  `alembic_version`, with no domain tables or funded wallets. The isolated test
  containers, network, and database volume were removed successfully.
- The original home-screen XML SHA-256 is unchanged:
  `4EDB8F1A46136317C0F7745EBE5157E785132339B16E228C2B4340DA66A1D9BE`.
- Android: the following command completed with **BUILD SUCCESSFUL**, producing
  both debug APKs, passing the existing single user-app sample unit test, and
  completing lint for both applications:

  ```powershell
  $env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'
  .\gradlew.bat :app:assembleDebug :app:testDebugUnitTest :app:lintDebug :sms-gateway:assembleDebug :sms-gateway:lintDebug --max-workers=2
  ```

- Lint: **0 errors**, 8 user-app warnings and 4 gateway warnings. User-app warnings
  cover the preserved target SDK, newer dependency/plugin versions, and existing
  unused color resources. Gateway warnings cover target SDK, backup-rule guidance,
  background overdraw, and an unspecified launcher icon. No lint suppression or
  home-screen changes were used to hide these warnings.
- Debug artifacts: `app/build/outputs/apk/debug/app-debug.apk` (7,487,642 bytes)
  and `android/sms-gateway/build/outputs/apk/debug/sms-gateway-debug.apk`
  (3,669,415 bytes).

The first Android build exposed a pre-existing mismatch: Core 1.19.0 required
compile SDK 37 while the project selected 36.1. Both modules now use the installed
SDK 37; the subsequent AAR metadata check passed. Docker initially had no running
engine; `docker desktop start` resolved that prerequisite.

## Blockers and verification limits

No remaining Sprint 0 build or backend-health blockers. Device/emulator launch,
instrumentation tests, visual interaction, and SMS delivery were not exercised.
The Android unit test is the existing generated sample; it is not evidence of
payment behavior. There is no payment or SMS behavior to test in this sprint.
The workspace remains outside Git; no repository initialization or commit was made.

## Local state and next command

`backend/.venv` contains installed development dependencies. The initializer created
an ignored `backend/.env` with a random local database password and the requested
limits, without printing secrets. Docker Desktop is running. Only the isolated
test stack was launched; the regular local stack is not left running.

From the project root, run:

```powershell
docker compose --env-file backend/.env up --build -d --wait
```

Then query `http://127.0.0.1:8000/health` and `/health/ready`. See README.md for
the complete setup and repeatable check commands.

## Next sprint

Proposed Sprint 1: agree participant authentication and empty ledger/schema acceptance
criteria before implementing them. Preserve integer-paise limits, backend authority,
test isolation, verified manual credits, and the approved visual design.
