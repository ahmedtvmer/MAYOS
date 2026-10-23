# MYOS Mobile (Flutter)

Shared Android and web client for the MYOS closed trial, backed by the FastAPI
service in the repository root. The basic player journey — register, log in,
onboard, view the automatic program, and open the dashboard — is exercised by
tests.

## Layout

- `lib/src/core/` — API client, secure token store, wire models, config.
- `lib/src/features/player/` — auth, conversational onboarding, dashboard, program.
- `lib/src/features/coach/` — coach capability and assignment screens.
- `lib/src/features/shared/` — cross-cutting UI.
- `test/` — service-contract flow test and capability-routing tests.

Android and web platform projects are included; no `flutter create` step is
needed on a clean checkout.

## Requirements

- Flutter stable with Dart 3.4+.
- For device/emulator builds: an installed Android SDK, accepted licenses, and a
  connected device or running emulator.
- For local web browser runs: Chrome available to Flutter as a device.

## Gates

From `mobile/`:

```bash
flutter pub get
flutter analyze
flutter test
```

## Running against the service

The API base URL is injected at build time with `--dart-define`. Debug builds
default to the Android emulator's host loopback (`http://10.0.2.2:8000`) and the
debug manifest permits cleartext for local development.

Google sign-in appears only when the Web OAuth client ID is supplied as the
`GOOGLE_WEB_CLIENT_ID` Dart define. Use the same ID configured on the API; omit
the define for a password-only build.

```bash
# Optional build-time Google configuration; do not commit the real value.
GOOGLE_WEB_CLIENT_ID="<web-client-id>.apps.googleusercontent.com"

# Debug, against a local service on the host machine.
flutter run \
  --dart-define=MAYOS_API_BASE_URL=http://10.0.2.2:8000 \
  --dart-define=GOOGLE_WEB_CLIENT_ID="$GOOGLE_WEB_CLIENT_ID"

# Release requires an explicit HTTPS base URL; the app fails fast otherwise.
cd mobile
GOOGLE_WEB_CLIENT_ID="$(sed -n 's/^GOOGLE_WEB_CLIENT_ID="\([^"]*\)"$/\1/p' ../.env)"
flutter build apk --release \
  --target-platform android-arm64 \
  --split-per-abi \
  -PappLinkHost=mayos-api.fly.dev \
  --dart-define=MAYOS_API_BASE_URL=https://mayos-api.fly.dev \
  --dart-define="GOOGLE_WEB_CLIENT_ID=$GOOGLE_WEB_CLIENT_ID"

# Build the shared web client for an HTTPS API.
flutter build web --release \
  --dart-define=MAYOS_API_BASE_URL=https://api.example.com \
  --dart-define=GOOGLE_WEB_CLIENT_ID="$GOOGLE_WEB_CLIENT_ID"
```

For local web development, set the service's `UI_BASE_URL` to the browser
origin (for example, `http://localhost:7357`) so CORS permits it, then run
`flutter run -d chrome --web-port 7357 --dart-define=MAYOS_API_BASE_URL=http://localhost:8000`.
Web requires a connection; offline workout drafts are Android-only. A release
web build must point at an HTTPS API on a host that permits its origin.

Onboarding uses deterministic rules and can complete without a model backend.
Chat and model-supported program requests need the hosted model configuration.
`SKIP_LLM_LOAD=true` starts without model warmup and is suitable for route-level
tests and the form-based onboarding flow.

## Testing notes

`test/auth_flow_test.dart` is a mocked HTTP contract test: it drives the real
`ApiClient`/`AuthController` stack (including the auth interceptor and 401
re-login) against an in-memory `HttpClientAdapter` that mirrors the service
routes and JSON shapes. It does not call a live backend. The structured intake
and removed legacy routes are covered against the real FastAPI app in
`tests/test_structured_intake.py` and `tests/test_svc_api.py`.

## Auth contract notes

- Registration and login post the legacy `trainee_id` wire field. Domain-facing
  auth methods use `username`; only the API client touches the wire field.
- `GET /auth/me` returns the immutable `account_id`, the legacy `trainee_id`,
  current `capabilities` (`player`, `coach`), and separate server-owned `plans`
  (`lifter`, `coach`). Eligible capabilities default to Free; a missing plan
  contract is treated as an invalid service response.
- ADR 007: a recovery email is mandatory. `GET /auth/email` returns
  `{"email": string | null}` and `POST /auth/email` accepts `{"email": string}`;
  a missing email routes to the recovery-email screen before dashboard or
  onboarding.
- The named-answer intake is the only onboarding path. It validates and saves
  answers through `/onboarding/intake/answers/{field}` and creates the first
  program through `/onboarding/intake/confirm`, using deterministic rules
  without hosted model inference.
- The bearer token is stored in the Android Keystore via
  `flutter_secure_storage`. Any authenticated `401` clears the session and
  routes back to login.
