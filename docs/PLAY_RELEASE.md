# Play Store release checklist (closed trial)

Owner-only steps for issue #43: the code side (privacy policy URL, in-app
entries, external deletion form, release signing, and this checklist) is in the
repository; creating the keystore, filling in Play Console, and signing off on
the legal text can only be done by the project owner. Work top to bottom; every
step is one command or one Play Console screen.

**URLs this release publishes** (host = the API host from `fly.toml`,
`https://mayos-api.fly.dev` today):

| Purpose | URL |
| :--- | :--- |
| Privacy policy (also linked in-app: login, register, Settings → About) | `https://<api-host>/privacy` |
| Account deletion request (also in-app: Settings → Profile → Delete account) | `https://<api-host>/account/delete-request` |

---

## 1. One-time API configuration

```bash
# Owner contact rendered on GET /privacy. Without it the page still serves,
# but with a placeholder and a warning in the logs.
fly secrets set PRIVACY_CONTACT_EMAIL="you@example.com"
```

- [ ] `PRIVACY_CONTACT_EMAIL` is set and the address is one you actually read.
- [ ] `curl -sI https://<api-host>/privacy` returns `200` and
      `cache-control: public, max-age=3600`.
- [ ] `curl -s https://<api-host>/privacy` shows your contact address (not the
      placeholder).
- [ ] `curl -sI https://<api-host>/account/delete-request` returns `200`.

## 2. Legal sign-off (owner, before publishing the URL)

- [ ] Read `docs/PRIVACY_POLICY.md` — it is the single source of truth that
      `GET /privacy` renders. Confirm every statement is true for your
      deployment, especially the hosted-model provider name (DeepInfra by
      default, `LLM_API_BASE`) and the retention windows.
- [ ] Replace the operator wording if you publish under a legal name/entity
      ("the MAYOS project" is a placeholder).
- [ ] Confirm the children statement: the policy says the service is **not
      directed at children under 16**; the repository itself states no age
      floor, so adjust the number to your intended audience and keep the Play
      target-audience setting in step 7 consistent.
- [ ] Bump `POLICY_VERSION` / `POLICY_EFFECTIVE_DATE` in
      `service/privacy_policy.py` whenever the text changes.

## 3. Generate the upload keystore (once)

```bash
keytool -genkeypair -v \
  -keystore ~/keystores/mayos-upload.jks \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias mayos-upload
```

- [ ] Choose a strong password and store it (and the `.jks`) in a password
      manager / offline backup. **Losing the upload key means you cannot
      publish updates** unless Play App Signing recovery is set up.
- [ ] The `.jks`/`.keystore` file and `key.properties` are gitignored
      (`mobile/android/.gitignore` and the root `.gitignore`); never commit
      them.

## 4. `mobile/android/key.properties`

Create `mobile/android/key.properties` (gitignored):

```properties
storePassword=<keystore password>
keyPassword=<key password>
keyAlias=mayos-upload
# Relative paths resolve against mobile/android/; absolute paths work too.
storeFile=../keystores/mayos-upload.jks
```

- [ ] A **release** build fails with a clear message when this file is missing
      or incomplete (verify once: `flutter build apk --release` without it must
      fail with the "Release signing is not configured" message). Debug builds
      and `flutter test` keep working either way.

## 5. Certificates and App Links

```bash
# Your upload key (the one in key.properties):
keytool -list -v -keystore ~/keystores/mayos-upload -alias mayos-upload | grep -A1 'SHA256'
```

- [ ] Take the Play Console → **Setup → App integrity → App signing key
      certificate** SHA-256 fingerprint (Google generates it on first upload).
- [ ] Set **both** fingerprints (upload key **and** Play App Signing key),
      comma-separated:

```bash
fly secrets set ANDROID_APP_SHA256_CERT_FINGERPRINTS="AA:BB:…,DD:EE:…"
```

  Without them `/.well-known/assetlinks.json` returns 404 and the password-reset
  App Link falls back to the hosted page (the reset still works, it just opens
  the browser instead of the app).

## 6. Build the signed artifact

```bash
cd mobile
flutter pub get
flutter build appbundle --release \
  --dart-define=MAYOS_API_BASE_URL=https://<api-host>
# → build/app/outputs/bundle/release/app-release.aab
```

- [ ] `MAYOS_API_BASE_URL` is **required** in release builds
      (`mobile/lib/src/core/config.dart` fails fast without it) and must be
      https.
- [ ] The bundle is signed with the upload key (`key.properties`), not the
      debug key.
- [ ] Version code/name come from `mobile/pubspec.yaml`
      (`version: 0.1.0+1` → `versionCode 1`, `versionName 0.1.0`); bump it for
      every upload.

### Launcher icon (regenerate whenever the logo changes)

The Android launcher icon comes from `assets/mayos-android-logo.png`, copied
into `mobile/assets/` (the root original is never modified) and rendered by
the `flutter_launcher_icons` dev dependency configured in `mobile/pubspec.yaml`:

```bash
cd mobile
flutter pub get
dart run flutter_launcher_icons
```

- [ ] Commit the regenerated `mobile/android/app/src/main/res/` files together
      with the logo change: every-density `mipmap-*/ic_launcher.png`, the
      Android 8+ adaptive icon (`mipmap-anydpi-v26/ic_launcher.xml`,
      `drawable-*/ic_launcher_foreground.png`, `values/colors.xml`).
- [ ] `ic_launcher_background` (`#01183D`) is sampled from the logo's navy
      tile; update it in `mobile/pubspec.yaml` if the logo's navy changes.
- [ ] The foreground PNG (`mobile/assets/mayos-android-logo-foreground.png`)
      is the M mark alone on transparent, scaled so every glyph pixel sits in
      the 66dp safe zone of the 108dp canvas — hence
      `adaptive_icon_foreground_inset: 0`. It is a committed input; re-derive
      it from the logo if the mark changes.
- [ ] Android only: `ios: false`, no `web:` block — iOS/web icons and splash
      screens are out of scope for this pipeline.

## 7. Play Console listing

- [ ] **Create the app** (free, app type: app; not a game).
- [ ] **Default store listing**: title, short/full description, screenshots,
      feature graphic. Describe it as a free invitation-only closed trial.
- [ ] **Privacy policy URL**: `https://<api-host>/privacy`.
- [ ] **App content → Data safety**: complete from §8 below.
- [ ] **App content → Content rating**: complete the IARC questionnaire
      (fitness/training app; health-adjacent self-reported data, no violence,
      no user-to-user messaging).
- [ ] **App content → Target audience**: choose the age group you confirmed in
      step 2 (the policy says 16+), and declare it is **not** designed for
      families.
- [ ] **App content → Ads**: no ads, no ads declaration required.
- [ ] **Account deletion**: Play asks for a deletion URL when the app handles
      accounts — enter `https://<api-host>/account/delete-request` (and mention
      the in-app path, which the form page links back to).
- [ ] **Testing → Closed testing**: create a closed track, **invite-only**,
      price **Free**. Add tester email addresses (or a Google Group) for the
      invitation list; keep the track internal-to-testers until launch.
- [ ] **Pricing & distribution**: free; select the countries for the trial;
      confirm no paid offers exist during the closed trial.

## 8. Data safety form (answer key, derived from `docs/PRIVACY_POLICY.md`)

**Data types collected** — map each row to the matching Play category:

| Play data type | Collected | Required / optional | Purpose | Shared with |
| :--- | :--- | :--- | :--- | :--- |
| **Personal info — username** | Yes | **Required** to create and use an account | App functionality (sign-in), account management | No one (processed by service providers only) |
| **Personal info — email address** (recovery email) | Yes | **Required**: the app blocks dashboard and onboarding until one is added (ADR 007 recovery gate) | App functionality (password recovery), account management | No one |
| **Health and fitness — body data**: weight, height, age, gender, body proportions, injuries/limitations free text | Yes | Optional — you choose what to enter | App functionality (training) | No one |
| **Health and fitness — exercise history**: workouts, sets, weights, reps, effort (RIR/RPE), readiness, personal records, training schedule and pauses, check-ins | Yes | Optional — you choose what to log | App functionality (training and coaching) | No one |
| **User content**: onboarding answers, assistant chat, program-request text | Yes | Optional | App functionality (AI features) | No one |
| **App activity / logs**: operational server logs (IP, path, time) and per-account model-usage records | Yes | Collected automatically (required for operation and security) | Security, app functionality (cost/limits) | No one |

**Questions:**

| Play question | Answer |
| :--- | :--- |
| Data collected | The types in the table above: username, recovery email, health/fitness data, user content, and logs. Nothing else — no contacts, no location, no device identifiers, no advertising IDs |
| Data shared | **No data sold, no data shared for advertising, no tracking.** Data *is* processed by service providers: the hosted model provider (AI features) and the SMTP provider (emails) |
| Data processed securely | Yes — encrypted **in transit** (https/TLS) |
| Data deletion available | **Yes**, both in-app (Settings → Profile → Delete account) and on the website (`https://<api-host>/account/delete-request`) |
| Required or optional | **Username and recovery email are required**; training, health, and AI content are optional; logs are collected automatically |
| Purpose | App functionality, account management, security, and AI features — not analytics, not advertising, not product improvement by third parties |
| Independent verification | No |

Keep this table and `docs/PRIVACY_POLICY.md` in sync: Play rejects a Data
safety form that contradicts the published policy.

## 9. Smoke checks before inviting testers

- [ ] Fresh install opens the signed-out login screen; **Privacy policy** opens
      `https://<api-host>/privacy` in the browser.
- [ ] **Create account** screen shows the Privacy policy link next to the
      consent row.
- [ ] Register, add a recovery email, complete onboarding.
- [ ] Settings → About → **Privacy policy** opens the same URL.
- [ ] Settings → Profile → **Delete account** works in-app.
- [ ] In a browser (no app), open `https://<api-host>/account/delete-request`,
      enter wrong credentials → generic refusal; then delete a throwaway
      account with the right credentials → success, and the username no longer
      signs in.
- [ ] Trigger the form's rate limit (11 quick submissions) → HTTP 429.
- [ ] Password-reset email link opens the app via the App Link (or the hosted
      page when the app is absent).
