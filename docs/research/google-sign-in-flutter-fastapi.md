# Research: Google sign-in for Flutter (Android + web) with FastAPI verification

Researched 2026-09-27 for wayfinder ticket #103 (map #102). All claims cite first-party
sources: pub.dev / flutter/packages source, Google Identity docs, Android developer docs,
google-auth source and PyPI, and Apple's App Store guidelines.

## TL;DR

- Use **`google_sign_in` 7.2.0** (latest stable on pub.dev; 7.0.0 was the breaking rewrite).
  It is a singleton (`GoogleSignIn.instance`), must be `initialize()`d exactly once, and
  splits **authentication** (who you are, ID token) from **authorization** (scopes, access
  tokens, server auth codes). MAYOS only needs authentication.
- **Android** (`google_sign_in_android` 7.2.17) uses Credential Manager. It needs an
  *Android* OAuth client (package name + SHA-1 per signing key) **and** a *Web application*
  OAuth client whose ID is passed as `serverClientId`. The ID token's `aud` is the **web
  client ID**.
- **Web** (`google_sign_in_web` 1.1.3) uses Google Identity Services. `authenticate()` is
  not supported and throws; you must show the SDK-rendered button (`renderButton()`), and
  `attemptLightweightAuthentication()` triggers One Tap. The result carries an **ID token**
  (the GIS `credential` JWT), with the web client ID as `aud`. It expires after an hour and is
  not renewed, so the backend must exchange it once for a MAYOS session JWT.
- **Server:** verify with **`google-auth`** (2.58.1, 2026-09-24):
  `google.oauth2.id_token.verify_oauth2_token(token, requests.Request(), audience)`.
  It checks the signature, `exp`, and `iss ∈ {accounts.google.com, https://accounts.google.com}`.
  `audience` accepts a str or a list. Key accounts on `sub`, never on `email`.
- **Console:** one Google Cloud project with the Google Auth Platform configured (Branding,
  Audience, Data Access with `openid email profile`). Create one Web client and one Android
  client per signing SHA-1 (debug, release, Play App Signing). External user type. Only
  basic scopes, so no verification is needed and the app can be published to production.
  In Testing mode, access is limited to 100 test users.
- **Branding:** on web the button must be the GIS-rendered one, which has a **400 px max
  width**. That conflicts with the map's "full-width button" on wide screens. On Android you
  may draw your own button following the guidelines (Google Sans Medium 14/20, standard
  colour "G", light/dark/neutral themes). The label is "Sign in with / Sign up with / Continue
  with Google". It must be at least as prominent as other third-party options.

## 1. Flutter client: `google_sign_in` v7

### Versions (checked 2026-09-27)

| Package | Version | Notes |
|---|---|---|
| `google_sign_in` | 7.2.0 (≈ Sep 2025), Dart ≥ 3.7 | 7.0.0 breaking rewrite; 7.2.0 added `clearAuthorizationToken`. Unreleased `NEXT` bumps to Flutter 3.41 / Dart 3.11. |
| `google_sign_in_android` | 7.2.17 (≈ Aug 2026) | Credential Manager based |
| `google_sign_in_web` | 1.1.3 (≈ Mar 2026) | GIS based |

Sources: https://pub.dev/packages/google_sign_in/versions,
https://pub.dev/packages/google_sign_in_android, https://pub.dev/packages/google_sign_in_web,
https://github.com/flutter/packages/blob/main/packages/google_sign_in/google_sign_in/CHANGELOG.md

The 7.0.0 changelog: "The `GoogleSignIn` instance is now a singleton. Clients must call and
await the new `initialize` method before calling any other methods on the instance.
Authentication and authorization are now separate steps. Access tokens and server auth codes
are obtained via separate calls."

The platform minimums on pub.dev are Android SDK 21+ and web. The `main` README now states
Android 24+ for the latest endorsed implementations, so pin and check when adding the dependency.

### API shape

```dart
final signIn = GoogleSignIn.instance;
await signIn.initialize(clientId: webClientIdOnWebOnly, serverClientId: webClientId /* Android */);
signIn.authenticationEvents.listen(onEvent);      // single source of truth for sign-in state
signIn.attemptLightweightAuthentication();       // silent / One Tap; do not await on web
if (signIn.supportsAuthenticate()) {
  await signIn.authenticate();                    // Android: user-initiated, from our own button
} // else (web): show renderButton() from google_sign_in_web
// On the resulting GoogleSignInAccount: account.authentication.idToken -> POST to backend
```

- `authenticate()` is only valid where `supportsAuthenticate()` is true (native). Web
  "returns false for `supportsAuthentication`, and will throw if `authenticate` is called".
- `authorizationClient` (`authorizationForScopes`, `authorizeScopes`, `authorizeServer`)
  is for API scopes and server auth codes. MAYOS does not need it. Signing in only requires
  the ID token.

Source: google_sign_in README and google_sign_in_web README (flutter/packages `main`).

### Android specifics

- The implementation uses Android **Credential Manager**.
- Required: an **Android** OAuth client (package name + SHA-1) and a **Web** OAuth client.
  Pass the web client ID as `serverClientId`, or have it present in `google-services.json` as an
  `oauth_client` with `client_type: 3`.
- Typical misconfiguration symptoms: `GoogleSignInException` with `clientConfigurationError`,
  unexpected `canceled`, or sign-in that works in one build configuration but not another. The
  cause is usually a "missing or incorrect signing SHA for one or more build configurations".
  Register the SHA-1 of the **debug keystore, the upload/release key, and the Play App Signing
  key** separately.
- Credential Manager's ID token `aud` = the **web client ID** passed as `serverClientId`
  (Android docs: "Use this as the `serverClientId`" … "The `aud` claim must match your
  configured client ID"). In a Flutter build, the `azp` claim is the Android client.
- Android guidance is to offer both the bottom sheet (automatic / authorized accounts) and a
  persistent button. The plugin maps these to `attemptLightweightAuthentication()` and
  `authenticate()`.

Sources: https://pub.dev/packages/google_sign_in_android,
https://developer.android.com/identity/sign-in/credential-manager-siwg

### Web specifics

- Uses the **Google Identity Services (GIS)** SDK, which "only allows signing in using UI
  provided by the SDK". You render the button with `renderButton({GSIButtonConfiguration?
  configuration})` (import `google_sign_in_web` directly) and listen to `authenticationEvents`.
- `attemptLightweightAuthentication()` calls `requestOneTap()`. The source notes: "One tap
  does not necessarily return immediately, and may never return, so clients should not await
  it." The plugin initializes GIS with `auto_select: true`.
- **Token returned:** the GIS `CredentialResponse.credential`, a Google **ID token JWT**,
  surfaced as `idToken`. There is no access token from authentication. Access tokens and server
  codes come only from `authorizationClient` and always need user interaction on web
  (`authorizationRequiresUserInteraction() => true`).
- "Once the token expires (after 3600 seconds), if you need to use the `idToken` again you must
  trigger a new authentication flow". "The GIS SDK does not renew authentication sessions."
  So the backend must mint its own MAYOS session, and it must not keep re-verifying Google tokens.
- Setup: `<meta name="google-signin-client_id" content="…apps.googleusercontent.com">` in
  `web/index.html` (or pass `clientId`). Add the app's origins to **Authorized JavaScript
  origins**, with `http://localhost` **and** `http://localhost:<port>` for development. Run
  with a fixed port: `flutter run -d chrome --web-hostname localhost --web-port 7357`.
- Headers: for local HTTP testing use `Referrer-Policy: no-referrer-when-downgrade`. If
  FedCM is off, the popup flow needs `Cross-Origin-Opener-Policy: same-origin-allow-popups`.
  This matters if the FastAPI/static server sets COOP.
- FedCM: `use_fedcm_for_prompt` is now "deprecated … and will be ignored", because One Tap runs
  through the browser's FedCM. `use_fedcm_for_button` is optional and defaults to false. The One
  Tap display-moment callbacks (`isDisplayed()` and similar) were removed, so UI must not
  depend on knowing whether One Tap showed.

Sources: https://pub.dev/packages/google_sign_in_web,
flutter/packages `google_sign_in_web/lib/google_sign_in_web.dart` and `lib/src/gis_client.dart`,
https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid,
https://developers.google.com/identity/gsi/web/reference/js-reference,
https://developers.google.com/identity/gsi/web/guides/fedcm-migration

## 2. FastAPI verification

### Library

**`google-auth`** (PyPI `google-auth`, 2.58.1 released 2026-09-24, Python ≥ 3.10). Google's
own verification guide uses it. It needs the `requests` transport (`google-auth[requests]` or
`requests` installed).

```python
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

_request = google_requests.Request()   # reuse; caches nothing by itself, see note below

def verify_google(token: str, web_client_id: str) -> dict:
    info = id_token.verify_oauth2_token(
        token, _request, audience=web_client_id, clock_skew_in_seconds=10,
    )  # raises ValueError / google.auth.exceptions.GoogleAuthError on any failure
    return info
```

- Signature: `verify_oauth2_token(id_token, request, audience=None, clock_skew_in_seconds=0)`.
  Internally `verify_token(..., audience: str | list[str] | None, ...)` accepts a **list** of
  audiences.
- It checks the signature against Google certs, `exp`/`iat` (with skew), and `aud`. The issuer
  is checked against `_GOOGLE_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]`.
  A wrong issuer raises `GoogleAuthError("Wrong issuer…")`.
- Always pass `audience`. With `None`, the audience is not checked.
- The certs are fetched on each call via the transport. For throughput, wrap the `Request` in
  a caching session (e.g. `cachecontrol`) or cache it at the app level. This is optional at
  MAYOS scale.

Sources: https://github.com/googleapis/google-auth-library-python/blob/main/google/oauth2/id_token.py,
https://pypi.org/project/google-auth/,
https://developers.google.com/identity/gsi/web/guides/verify-google-id-token

### What to verify

| Claim | Rule | Source |
|---|---|---|
| `aud` | Must equal one of **your** client IDs. Both Android (`serverClientId`) and web tokens carry the **web client ID**, so a single allowed audience suffices. Accept a configured list anyway, in case of a future iOS client. | verify-google-id-token; OIDC doc |
| `iss` | `accounts.google.com` or `https://accounts.google.com` (library enforces) | OIDC doc |
| `exp` | Not passed (library enforces) | verify-google-id-token |
| `azp` | Client ID of the presenter. It is informational here (Android client on Android). Do not require it to equal `aud`. | OIDC doc |
| `sub` | "unique among all Google Accounts and never reused". This is **the** stable key: store `(provider='google', subject=sub)`. | OIDC doc |
| `email` / `email_verified` | "Don't use the `email` field as a unique identifier … Always use the `sub` field." `email_verified` means Google verified the address at some point, but "ownership of the third party email account may have since changed". Use it only as a display/prefill hint, never for account matching. | OIDC doc; verify-google-id-token |
| `hd` | Only present for Workspace users. Not needed for MAYOS. | OIDC doc |

This confirms the map's standing decision: a **Linked sign-in is keyed on provider +
subject and never matched by email**.

Optional hardening: pass a `nonce` from the client (`initialize(nonce:)` is exposed by the
plugin and GIS) and check it server-side. Keep the verification endpoint rate-limited like
`/auth/login`.

## 3. Google Cloud console objects

The console area is now called **Google Auth Platform** (Branding, Audience, Clients, Data Access).

| Object | Purpose |
|---|---|
| Google Cloud project | Holds everything below |
| **Branding** | App name, logo, support email, **authorized domains**, homepage, privacy policy, and ToS links, all hosted on authorized domains. Brand verification is needed for the app name/logo to show on the consent screen. |
| **Audience** | User type **External**. Publishing status **Testing** restricts use to ≤ 100 listed test users. **In production** opens it to any Google account. |
| **Data Access** | Scopes `openid`, `email`, `profile`. "The default scope (email, profile, openid) is sufficient". These are non-sensitive, so no app verification is required. |
| **Client: Web application** | Its ID is used both as the web `clientId` and as Android's `serverClientId`, and it is the backend's expected `aud`. Authorized JavaScript origins: prod origin(s) plus `http://localhost` and `http://localhost:<port>`. No redirect URI is needed for the popup flow. |
| **Client(s): Android** | Package name plus SHA-1. Add one per signing certificate: debug, upload/release, and Play App Signing. |

Human checklist items for the slicing ticket: the SHA-1 values
(`./gradlew signingReport` / Play Console → App integrity), prod web origin(s), and the
privacy-policy URL on an authorized domain.

Sources: https://developers.google.com/identity/gsi/web/guides/get-google-api-clientid,
https://support.google.com/cloud/answer/15549945,
https://developer.android.com/identity/sign-in/credential-manager-siwg

## 4. Branding rules for the button

From https://developers.google.com/identity/branding-guidelines (updated 2026-07-07):

- Text: "Sign in with Google", "Sign up with Google", or "Continue with Google". Localization
  is encouraged. Never write just "Google".
- Themes: **Light** (fill #FFFFFF, 1px inside stroke #747775, text #1F1F1F), **Dark** (fill
  #131314, stroke #8E918F, text #E3E3E3), **Neutral** (fill #F2F2F2, no stroke, text #1F1F1F).
- Font: **Google Sans Medium 14/20** (no longer Roboto).
- Logo: the standard-colour "G" on a white background. Do not recolour, resize independently,
  use monochrome, or substitute a custom icon.
- Padding (Android/web): 12px left of the logo, 10px after the logo, 12px after the text.
  Rectangular or pill shapes are allowed, and icon-only is allowed only with the button boundary.
- "The Sign in with Google button should be displayed at least as prominently as other third
  party sign-in options."
- "Our Google Identity Services SDKs render a Sign in with Google button that always adheres to
  the most recent Google branding guidelines. They are the recommended way".
- Pre-approved assets: https://developers.google.com/static/identity/images/signin-assets.zip

Platform consequences for MAYOS:

- **Web:** you must use the GIS-rendered button. Its `width` is a minimum and "the maximum width
  is 400 pixels". Options: `text` (`signin_with`, `signup_with`, `continue_with`, `signin`),
  `shape` (`rectangular`, `pill`, `circle`, `square`), `theme` (`outline`, `filled_blue`,
  `filled_black`), and `logo_alignment` (`left`, `center`). "Full-width" therefore means full
  width up to 400 px, centred. The button is an iframe/HTML element, so it will not match
  MAYOS typography exactly and follows the browser/Google locale.
- **Android:** a custom Flutter button is allowed if it follows the rules above. Pick Light or
  Dark per app theme and bundle the official "G" asset.

## 5. Apple as a second provider later

- **Makes it easier:** a provider-neutral `(provider, subject)` identity table. Apple's
  `userIdentifier`/`sub` is the stable key (per Apple developer team), and the email may be a
  private relay address. Apple returns email and name **only on the first sign-in**, so the
  first-sign-in flow already has to create the account and ask for a username. That matches the
  map's Google flow. An `aud`/issuer verification layer parameterized per provider also helps
  (Apple: `iss = https://appleid.apple.com`, `aud` = bundle ID or Services ID, JWKS at Apple).
- **Makes it harder / constraints:**
  - App Store Guideline **4.8**: an iOS app that uses Google Sign-In for the primary account
    "must also offer as an equivalent option another login service" that limits data to name
    and email, allows email hiding, and does no ad tracking without consent. In practice that
    means Sign in with Apple, so iOS launch and Apple sign-in must ship together. MAYOS's own
    username/password system is an exemption only when it is the sole method.
  - `sign_in_with_apple` (8.2.0) supports Android and web, but needs an Apple **Services ID**,
    registered return URLs, and a server callback for the Android/web redirect. That is more
    server work than Google. The package recommends validating the `authorizationCode` with
    Apple server-side.
  - Never match Apple to Google accounts by email (relay addresses differ). A person who wants
    both links them from Settings, the same way as "Connect Google".
  - Branding rule: the Google button must be at least as prominent as the Apple one (and Apple
    has its own equal-prominence rules).

Sources: https://developer.apple.com/app-store/review/guidelines/ (4.8),
https://pub.dev/packages/sign_in_with_apple

## 6. Implications for MAYOS (for the grilling/slicing ticket)

1. Flow: client obtains an ID token, then calls `POST /auth/google` with `{id_token}`. The server
   verifies it (aud = web client ID), then looks up `(google, sub)`:
   - If found, it issues the normal MAYOS HS256 session JWT (same epoch/revocation model as
     `docs/AUTHENTICATION.md`).
   - If not found, it returns a short-lived signed "pending linked sign-in" ticket, and the client
     asks for a username, which then creates the account.
   - "Connect Google" in Settings is an authenticated call that attaches `(google, sub)` to the
     current account. It fails if the pair is already linked elsewhere.
2. Accounts live in per-user ledgers (`docs/AUTHENTICATION.md` §1), so the `(provider, subject)
   → account` index must live in the **shared catalog**, like recovery identity. A per-ledger
   lookup cannot find an account from a Google token alone.
3. Config: `GOOGLE_WEB_CLIENT_ID` (backend audience, web `clientId`, Android `serverClientId`).
   The Android client ID is not needed in code; the console match is on package name plus SHA-1.
4. Web: design the sign-in screen around a ≤ 400 px GIS button. The web server must not send
   `Cross-Origin-Opener-Policy: same-origin` without `-allow-popups`.
5. Do not rely on Google tokens after the exchange: web ID tokens expire in 1 h and are not
   renewed.
