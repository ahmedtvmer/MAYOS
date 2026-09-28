# Google sign-in: Google Cloud setup

The operator runbook for issue #112. Only the owner of the Google account can
do the Google Cloud steps. They do not block writing code: backend and Flutter
tests use a fake ID-token verifier. They only block the final end-to-end check
on a real device and in a browser.

Background: #103 (research) and #104 (flows and account linking). The code that
reads these values is #113 (backend) and #115 (Flutter).

## What is secret and what is not

An OAuth **client ID** is public: it ships inside every app build and web page.
Record the client IDs in a comment on #112. No client *secret* is used: the
backend only verifies ID tokens against the web client ID, and neither the
Android nor the web flow needs one. Don't create or download one.

## 1. Google Auth Platform

- **Branding:** app name `MAYOS`, the logo from `assets/`, a support email, the
  privacy policy URL (the API serves it at `GET /privacy`, see ADR 046), and the
  web host as an authorized domain. For the trial that host is the Cloudflare
  Pages origin from #129 (ADR 048), not `mayos.app` (#132 tracks the move).
- **Audience:** External, left in **Testing**, with your own and your testers'
  Google accounts added as test users (at most 100). Publish to production
  before general release.
- **Data Access:** `openid`, `email`, `profile` only. These are non-sensitive,
  so no verification review is needed.

## 2. Web OAuth client (the token audience)

Create one OAuth client of type **Web application**. Authorized JavaScript
origins:

- the production web origin (the Pages origin from #129, e.g.
  `https://mayos.pages.dev`)
- `http://localhost`
- `http://localhost:7357` (the Flutter web dev port used in `mobile/README.md`)

No redirect URIs are needed. Its client ID is `GOOGLE_WEB_CLIENT_ID` everywhere
below. It is the token audience on **both** Android and web.

## 3. Android OAuth clients

Create one OAuth client of type **Android** per signing key. Every one uses the
package name `com.mayos.mayos_mobile` (`applicationId` in
`mobile/android/app/build.gradle.kts`) and that key's **SHA-1**. The app never
uses these client IDs directly. Google matches them by package name and SHA-1,
and a sign-in from a build signed by a key without a client fails with
`DEVELOPER_ERROR` or a similar configuration error.

| Key | Needed for | Get the SHA-1 |
| --- | --- | --- |
| Debug keystore | `flutter run` on a device or emulator | `keytool -list -v -keystore ~/.android/debug.keystore -alias androiddebugkey -storepass android \| grep 'SHA1:'` |
| Upload key | release builds you install yourself | `keytool -list -v -keystore ~/keystores/mayos-upload -alias mayos-upload \| grep 'SHA1:'` (the keystore in `mobile/android/key.properties`, see `docs/PLAY_RELEASE.md`) |
| Play App Signing key | builds installed from Play | Play Console, Setup, App integrity, App signing key certificate, SHA-1 |

Each machine you build debug builds on has its own debug keystore, so add one
debug client per machine. From `mobile/android`, `./gradlew signingReport`
prints the SHA-1 of every configured key at once.

The same keys' **SHA-256** fingerprints go in
`ANDROID_APP_SHA256_CERT_FINGERPRINTS` for App Links. That is a separate
setting (`docs/PLAY_RELEASE.md`) and does not replace these clients.

## 4. Backend

Set `GOOGLE_WEB_CLIENT_ID=<web client id>` in the API's environment (for Fly:
`fly secrets set GOOGLE_WEB_CLIENT_ID=...`, even though it is not secret, so it
sits with the rest of the runtime config). When it is unset, the Google
endpoints return 503 and nothing else changes (#113).

## 5. App builds

Pass the same web client ID to every Android and web build:

```bash
flutter run --dart-define=MAYOS_API_BASE_URL=http://10.0.2.2:8000 \
  --dart-define=GOOGLE_WEB_CLIENT_ID=<web client id>

flutter build appbundle --release --dart-define=MAYOS_API_BASE_URL=https://<api-host> \
  --dart-define=GOOGLE_WEB_CLIENT_ID=<web client id>

flutter build web --release --dart-define=MAYOS_API_BASE_URL=https://<api-host> \
  --dart-define=GOOGLE_WEB_CLIENT_ID=<web client id>
```

Without it the Google button is hidden and password sign-in works as before
(#115).

## 6. Web host headers

Google's web sign-in button opens a popup that must be able to message the
page. That breaks if the page is served with
`Cross-Origin-Opener-Policy: same-origin`. Unset, or `same-origin-allow-popups`,
is fine. Check the deployed origin:

```bash
curl -sI https://<pages-origin>/ | grep -i cross-origin-opener-policy
```

No output, or `same-origin-allow-popups`, passes. Cloudflare Pages sets no COOP
header by default, and the repo has no `_headers` file that adds one. The API's
own HTML pages (`svc/html.py`) are not the web app and don't matter here.

## 7. End-to-end check

Only after #113 and #115 have landed:

- [ ] On Android (debug build, then a Play build): a Google account with no
      MAYOS account reaches the username picker, picks a name, and lands in the
      app. Signing out and signing in again with Google goes straight in.
- [ ] The same on web, at the production origin and at `http://localhost:7357`.

Then comment on #112 with where the client IDs are recorded and close it.
