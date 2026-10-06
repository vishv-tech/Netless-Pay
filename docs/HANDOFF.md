# Sprint 3 handoff

Date: 2026-10-07. Scope: participant Kotlin/XML UI, Sprint 2 API integration,
secure device onboarding, timestamped read cache and optional local privacy lock.
Sprint 4 is not started. Historical Sprint 2 handoff is preserved in
[HANDOFF_SPRINT2.md](HANDOFF_SPRINT2.md).

Final status: **Sprint 3 implementation complete and accepted for now**, based on
the passing backend checks, 64 Android unit tests, both debug APK builds and
zero lint errors. UI instrumentation is deferred as explicitly directed by the
user. No further implementation changes or emulator troubleshooting are planned.

## Starting state and preserved work

The existing Android project was reused in place. Repository instructions,
README, architecture, roadmap, handoff, Android sources and actual backend
schemas/routes were inspected before editing. There is no Git repository in
this directory and no AGENTS.md was found. No reset, checkout or clean was used.
The existing Keystore credential foundation and Sprint 0/1/2 backend services,
authentication, migrations, grants and accounting invariants remain intact.
No backend source or PostgreSQL migration was changed in Sprint 3.

## Created and changed files

- Android application/navigation: `WalletApplication.kt`, rewritten
  `MainActivity.kt`, `MainViewModel.kt`, `ui/WalletFragments.kt`,
  `ui/WalletController.kt`, `ui/AppLock.kt`, `ui/Money.kt`.
- Data/API/cache: `data/WalletModels.kt`, `WalletApi.kt`,
  `ParticipantRepository.kt`, `WalletCache.kt`, updated `WalletDatabase.kt`.
  Room migration 1 -> 2 preserves preferences and adds participant-scoped
  confirmed-read cache. Exported Room version-2 schema is under `app/schemas/`.
- XML: activity shell and authentication, device, Home, Add Money, Profile,
  history and status fragment layouts; transaction row; shared light colors,
  typography/dimensions/component styles, API-qualified themes, icons,
  navigation menu and tint. No Compose conversion or second user project.
- Configuration: `app/build.gradle.kts`, `gradle/libs.versions.toml`, manifest,
  release/default and debug local-domain network security configuration.
  Optional `scripts/android-verification.init.gradle` changes only generated
  output location for OneDrive environments.
- JVM tests: `Sprint3Fakes.kt`, `ControllerTest.kt`, `RepositoryTest.kt`,
  `HttpWalletApiTest.kt`. Existing nine tests retained.
- Instrumentation: isolated `WalletTestRunner.kt` application/repository,
  `WalletNavigationTest.kt`, `WalletCacheMigrationTest.kt`; existing test retained.
- Documentation: README, ARCHITECTURE, ROADMAP, this handoff and new
  `docs/ANDROID_SETUP.md`. No real credentials, funds or bank details were added.

## Behavior

Activation redeems an administrator's token, waits for backend confirmation,
then navigates to login. Password/token fields are not restored from saved view
state and clear on submit. Login normalizes Indian phone numbers and optionally
binds a matching saved approved device. Startup reads encrypted credentials and
uses GET me to validate the session, then device and wallet reads. Expired/revoked
sessions clear authenticated UI state; outages retain potentially valid sessions.
Suspension/revocation errors remain generic, as required by the backend.

Connected endpoints: POST auth/redeem, auth/login, auth/logout, auth/logout-all;
GET me, me/wallet, me/transactions with offset/limit; GET/POST me/devices;
DELETE me/devices/{device_id}, all under `/api/v1`. No competing contracts,
financial mutation endpoint, SMS protocol or administrator UI was added.

Device secrets are received once into existing Keystore AES-GCM/AtomicFile
storage; never displayed or logged. Registration is pending until an administrator
approves it. Replacement erases the old local secret and cached wallet before
requesting replacement; a lost response requires new enrollment/approval.
Revocation is displayed only after backend confirmation. Logout clears local
session, device and cache even if backend logout is unavailable and reports
unconfirmed server revocation honestly. Subsequent login needs new enrollment.

Home uses a rounded cobalt card, hidden three-dot balance, Last confirmed time,
left Scan QR/right Enter UPI ID disabled actions, and working Home/Add Money/
Profile navigation. Add Money states pool details are unconfigured. Profile
shows only permitted own-participant/device information and privacy/logout tools.
History uses server pagination. No fake financial data appears in the app.

Local app lock uses AndroidX BiometricPrompt with supported biometrics or system
device credentials. Setup is optional after activation/login and from Profile.
Cold launch locks when enabled; a monotonic 30-second background timeout relocks.
Home/Profile can lock immediately, including while a request is in flight.
Balance hides on pause/background/lock. Cancellation/unavailability cannot bypass
it. Only nonsecret enabled/offered preferences persist; no custom PIN or prompt
result is stored. Unlock does not create a backend session or authorize payment.

Room is a participant-scoped timestamped read cache, not an authoritative ledger.
Only confirmed responses advance the timestamp. Offline/server failures show an
honest warning and Last confirmed data. Transaction history needs connectivity.
Account switching, replacement and logout prevent stale data crossing participants.
Debug URL defaults to 10.0.2.2; local-only HTTP exceptions are debug resources.
Release cleartext is prohibited and unconfigured release URL is empty. No TLS
bypass, network credential/body logger or automatic mutation retry is present.

## Verification

- Isolated `python backend/scripts/check_compose.py`: exit 0; **113 passed**,
  0 failed/skipped, one upstream Starlette/HTTPX deprecation warning; pytest
  220.82 seconds. Includes existing accounting concurrency/reconciliation,
  authentication, migration upgrades/schema/role checks and append-only protections.
- Health/readiness 200; database outage readiness 503/liveness 200; restart 200.
  Public wallets/ledger remained empty. Disposable project/volume removed.
- Final Android verification: **BUILD SUCCESSFUL**, exit 0, **64 unit tests**,
  0 failures/errors/skips; debug APK and debug instrumentation APK built;
  **lint 0 errors, 21 warnings**. Full run took 5m 58s. Warnings: 10 target/tool/
  dependency update suggestions, 2 overdraw, 5 unused resources and 4 KTX style
  suggestions. No lint baseline or error suppression was introduced.
- UI instrumentation was **NOT completed**: the isolated API 37 emulator remained
  offline in adb. The instrumentation APK compiled successfully, but no UI or
  emulator Keystore test execution is claimed. Emulator troubleshooting was
  stopped at the user's explicit request; no further retries are planned.

Repeat exact commands in [ANDROID_SETUP.md](ANDROID_SETUP.md). No physical-device
verification is claimed. No screenshots have been captured. Earlier failed Android
runs exposed stale OneDrive generated-folder permissions, resource encoding/API
qualification errors and two incorrect test expectations; these were diagnosed
and corrected. Only verified generated build outputs were removed.
Final build outputs were generated beneath `%TEMP%/OfflineWallet-Sprint3-verify`
using the optional init script; final APK, lint and unit reports were copied into
`build/sprint3-verification/`. Existing app sources were never moved.

## Limitations and Sprint 4

No known unresolved code defects or implementation blockers were identified by
the completed checks. This does not establish defect-free device behavior:
instrumentation, system biometric/device-credential interaction and end-to-end
Android-to-backend demonstration remain unverified. The deferred emulator check
does not block the user's accepted Sprint 3 wrap-up. Lint's 21 warnings and the
upstream backend deprecation warning remain as documented above.

Manual admin-confirmed phone ownership and device approval remain limitations;
there is no OTP. No real API/device demonstration, physical biometric enrollment,
rooted-device, backup/restore or remote HTTPS deployment validation is claimed.
Room cache is app-private plaintext and may contain permitted personal/financial
read data; local lock is UI privacy, not protection against a compromised OS.
Keystore key loss requires enrollment again. Generic backend errors cannot reveal
whether an account was suspended or a device/session revoked.

Sprint 4 must be separately authorized: versioned device-authenticated SMS request
protocol, replay/expiry protection, gateway provisioning/transport/durable retries,
idempotent ledger integration and backend-confirmed pending/failure/success replies,
with isolated duplicate/tamper/reorder/outage/concurrency tests. Real funding,
admin dashboard, QR scanning and external UPI remain separately scoped later work.
This is a small noncommercial college prototype, not production-ready or
regulatory-approved.
