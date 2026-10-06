# Android local backend and emulator setup

This is a small noncommercial college research prototype. Sprint 3 provides
participant authentication, device onboarding and read-only wallet screens.
It does not enable deposits, transfers, QR scanning, UPI or SMS payments.

## Backend and activation

From the project root in PowerShell, start Docker Desktop's Linux engine:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\scripts\init-local.ps1
docker compose --env-file backend/.env up --build -d --wait
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose --env-file backend/.env run --rm --no-deps migrate python -m app.bootstrap create-admin
```

The bootstrap command reads the first administrator's password interactively;
do not pass it as an argument. See README for policy, role provisioning and
administrator API instructions. Never delete the demonstration database volume
to upgrade it. No startup task seeds participants or funded wallets.

An administrator confirms phone ownership manually and enrolls the participant
through `POST /api/v1/admin/participants`. Deliver the single-use token privately.
In Android choose **Activate account**, enter that token and matching passwords,
then sign in using the normalized Indian mobile number. There is no unrestricted
registration, OTP verification or bank/UPI credential collection.

## Configure and install the Android app

Use Android Studio's installed JBR and the existing wrapper, not a new project:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:assembleDebug --max-workers=2
```

Debug defaults to `http://10.0.2.2:8000/`, the emulator alias for the host loopback
backend. One `WALLET_API_BASE_URL` Gradle property overrides this build setting:

```powershell
.\gradlew.bat :app:assembleDebug '-PWALLET_API_BASE_URL=http://10.0.2.2:8000/' --max-workers=2
```

The URL contains no credentials. Debug HTTP is allowed only for `10.0.2.2`,
`127.0.0.1` and `localhost`. Remote URLs require HTTPS, and release cleartext is
disabled. An unconfigured release has an empty URL and reports a configuration
error. Do not add secrets or tokens to Gradle properties or URL arguments.
TLS verification uses the platform defaults.

Start an AVD using Android Studio's Device Manager and install
`app/build/outputs/apk/debug/app-debug.apk`. A physical-device loopback workflow
may use `adb reverse tcp:8000 tcp:8000` and a debug `http://127.0.0.1:8000/` URL;
that workflow has not been physically verified. Do not expose local HTTP over
public networks. Production deployment is outside this prototype's scope.

## Device onboarding and recovery

After sign-in, register a device label. The app encrypts the one-time device
secret using Android Keystore-backed storage; it never displays or logs it.
The device starts pending. A trusted administrator inspects it and uses
`POST /api/v1/admin/devices/{device_id}/approve`. Tap **Check approval** to load
the wallet using the enrolling, device-bound session. A later login can use
the saved device. If an approved device is present but the session is unbound,
the app offers sign-in again with the saved device.

Replacement revokes the previous backend device and requires approval again.
The app clears the previous local secret and balance cache before sending the
replacement request. A lost response cannot recover the one-time secret:
register a replacement and obtain approval. If a saved device prevents login,
turn off **Use saved device** for password-only recovery. Revoked sessions/device
credentials cannot authorize wallet reads. Logout clears session, device secret
and cached data; subsequent login therefore needs enrollment again. Offline
logout reports that backend revocation could not be confirmed.

## Backend login and local app lock

After successful activation/login, **Set up app lock** and **Not now** are offered.
Profile can enable/manage it later. The system BiometricPrompt uses available
biometrics or the existing device screen lock; the app creates no custom PIN and
stores no biometric information or prompt result. No enrollment is forced.

When enabled, cold launch requires unlock, 30 seconds in the background relocks,
and Home's lock icon or Profile's **Lock app now** locks immediately. Cancellation
or unavailable authentication leaves the app locked. The confirmed erase-local-
data recovery option clears secrets/cache before disabling the lock. Local unlock
does not replace backend authentication and never authorizes a payment.

## Offline and unavailable actions

Home hides balance as exactly `•••` until tapped, and hides it again on background
or lock. Room retains only participant-scoped confirmed reads with **Last confirmed**
timestamps. Outages retain potentially valid sessions and show an honest warning;
cache is not live verification of account/device status. Known expired/revoked
sessions clear authenticated UI state. Transaction history requires connectivity.

Scan QR and Enter UPI ID remain visible and disabled. Add Money states that the
owner's pool-account details are unconfigured; it supplies no invented bank data.
Only administrator-verified deposits against authoritative bank records may ever
be credited in a future sprint. Internal wallet transfers will not initiate UPI
or bank transfers. Future SMS requests still require cellular service, while the
gateway and backend require connectivity.

## Repeat verification using isolated data

```powershell
python backend/scripts/check_compose.py
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --max-workers=2
# Only with a booted emulator/device:
.\gradlew.bat :app:connectedDebugAndroidTest --max-workers=2
```

Backend checks create their own disposable PostgreSQL project and random test
schemas; they do not use `backend/.env`. JVM HTTP tests use MockWebServer.
Instrumentation replaces the application repository with isolated synthetic data,
so it cannot contact the configured API or demonstration database. It also tests
the actual emulator Keystore adapter. Reports are under `app/build/reports/` and
`app/build/outputs/androidTest-results/`. Do not treat emulator tests as physical-
device verification. `FLAG_SECURE` intentionally prevents ordinary screenshots.

### OneDrive generated-output workaround

On this machine, OneDrive placeholder/reparse outputs caused Gradle snapshot and
directory-deletion errors. The optional init script changes only generated build
output location; the Android source/project remains in its existing directory.
Use an isolated temporary output folder and the same tasks:

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:OFFLINEWALLET_BUILD_OUTPUT=Join-Path ([System.IO.Path]::GetTempPath()) 'OfflineWallet-Sprint3-verify'
.\gradlew.bat -I scripts/android-verification.init.gradle :app:testDebugUnitTest :app:assembleDebug :app:lintDebug :app:assembleDebugAndroidTest --max-workers=2
# With a booted emulator/device, re-use the same output setting:
.\gradlew.bat -I scripts/android-verification.init.gradle :app:connectedDebugAndroidTest --max-workers=2
```

Reports and APKs are then beneath `$env:OFFLINEWALLET_BUILD_OUTPUT`, rather than
`app/build`. This override is optional and contains no backend URL or credential.
Build and emulator workloads may need to run sequentially on memory-limited hosts.
