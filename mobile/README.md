# MAYOS Mobile (Flutter)

Android player client for the MAYOS closed trial, backed by the FastAPI service
in the repository root. The basic player journey — register, log in, onboard,
view the automatic program, and open the dashboard — is exercised by tests.

## Layout

- `lib/src/core/` — API client, secure token store, wire models, config.
- `lib/src/features/player/` — auth, conversational onboarding, dashboard, program.
- `lib/src/features/coach/` — reserved placeholder for the coach console (#23).
- `lib/src/features/shared/` — cross-cutting UI.
- `test/` — service-contract flow test and capability-routing tests.

The Android platform project under `android/` is part of the repository; no
`flutter create` step is needed on a clean checkout.

## Requirements

- Flutter stable with Dart 3.4+.
- For device/emulator builds: an installed Android SDK, accepted licenses, and a
  connected device or running emulator.

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

```bash
# Debug, against a local service on the host machine.
flutter run --dart-define=MAYOS_API_BASE_URL=http://10.0.2.2:8000

# Release requires an explicit HTTPS base URL; the app fails fast otherwise.
flutter build apk --release --dart-define=MAYOS_API_BASE_URL=https://api.example.com
```

Onboarding, chat, and program generation need the model backend, so run the
service normally to exercise the player journey. `SKIP_LLM_LOAD=true` starts
without warmup and is suitable only for route-level tests; onboarding cannot
complete in that mode.

## Testing notes

`test/auth_flow_test.dart` is a mocked HTTP contract test: it drives the real
`ApiClient`/`AuthController` stack (including the auth interceptor and 401
re-login) against an in-memory `HttpClientAdapter` that mirrors the service
routes and JSON shapes. It does not call a live backend. The onboarding resume
contract is also covered against the real FastAPI app in
`tests/test_svc_api.py`.

## Auth contract notes

- Registration and login post the legacy `trainee_id` wire field. Domain-facing
  auth methods use `username`; only the API client touches the wire field.
- `GET /auth/me` returns the immutable `account_id`, the legacy `trainee_id`,
  and current `capabilities` (`player`, `coach`) read from the durable registry.
- ADR 007: a recovery email is mandatory. `GET /auth/email` returns
  `{"email": string | null}` and `POST /auth/email` accepts `{"email": string}`;
  a missing email routes to the recovery-email screen before dashboard or
  onboarding.
- ADR 016: onboarding shows a hosted-AI processing disclosure before any
  `/onboarding/start` or `/onboarding/step` request.
- `POST /onboarding/start` is load-or-start: it resumes saved progress and
  returns the assistant prompts so far. Explicit reset is `POST /onboarding/step`
  with `reset=true`.
- The bearer token is stored in the Android Keystore via
  `flutter_secure_storage`. Any authenticated `401` clears the session and
  routes back to login.
