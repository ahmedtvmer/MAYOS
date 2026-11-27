# Google Play launch checklist (issue #750)

Mirrors the checklist in GitHub issue #750 ("Google Play launch checklist —
personal account, free-only first release"). This document tracks what the
implementer has delivered in the repository and what remains owner-only.
#748 (assistant reply feedback/reports) ships in the same release, ahead of
this ticket, so its data and listing sentences are declared now; #749 (FCM
push) is still open — every "planned" mention below refers to #749 only.

Owner decisions (2026-11-17): Android launch on Google Play, **personal**
developer account, first release **free only**; Play Billing for Lifter Pro
comes after #740.

## Owner steps (unchanged, owner-only)

- [ ] Create the Play Console personal developer account; complete identity
      verification (US$25 one-time fee).
- [ ] Create the Firebase project for #749.
- [ ] Create the app-signing upload key (kept outside git); enrol in Play App
      Signing. See `docs/PLAY_RELEASE.md` §3–§5.
- [ ] Recruit **at least 12 testers**; new personal accounts must run a closed
      test with them opted in for 14 days before applying for production.

## Policy and listing (implementer prepares, owner submits)

- [x] **AI-generated content**: the store listing says the app uses AI in
      both languages (`docs/play/STORE_LISTING.md` → "AI disclosure").
      In-app reporting of assistant replies ships with #748 in the same
      release, ahead of this ticket, so the listing's "report a reply"
      sentence is part of the submitted listing, and the feedback data is
      declared in the Data safety form (`docs/play/DATA_SAFETY.md` →
      "Assistant reply feedback and reports" row).
- [x] **Account deletion**:
  - in-app deletion exists (Settings → Linked sign-in → Danger zone →
    Delete account);
  - public web page **delivered**: `web_landing/account-deletion.html`,
    served at `https://mayos.online/account-deletion`, linked from the
    landing site footer, in English and Arabic (RTL), reusing the existing
    rate-limited API endpoint `/account/delete-request` with a `mailto:`
    fallback to `founders@mayos.online`. No new API endpoint was needed.
- [x] **Privacy policy URL**: `https://api.mayos.online/privacy` (policy
      version 1.13, effective 2026-11-17). Covers assistant chats, feedback
      and reports (#748, in the same release as this ticket), health and
      fitness data, and every processor: Contabo (Germany), DeepInfra by
      default (AI), SMTP provider, PostHog EU, Sentry EU. **Push tokens are
      deliberately not described yet** — no push code exists before #749,
      and #749 must add the "Push notification tokens" section to the
      policy when it ships. Pin: `service/privacy_policy.py` →
      `POLICY_VERSION` / `POLICY_EFFECTIVE_DATE`.
- [x] **Data safety form** prepared, matching what the app collects today:
      `docs/play/DATA_SAFETY.md` (includes the crash-logs/Sentry row and the
      assistant reply feedback/reports row for #748, which ships in the same
      release; the single "do not declare until shipped" row is #749's).
- [ ] **Health apps declaration**, fitness category, and content rating
      questionnaire — guidance in `docs/play/DATA_SAFETY.md` §"Related
      declarations"; the questionnaire itself is owner work.
- [x] **Nutrition data** declared (#881): Fitness info and Health info rows in
      `docs/play/DATA_SAFETY.md`; Nutrition and the fitness disclaimer in both
      listings (`docs/play/STORE_LISTING.md`).
- [x] **Tester recruitment**: Google Group setup and EN/AR invite message in
      `docs/play/TESTERS.md` (#881).
- [x] **Program import files** covered by policy 1.16 "Program import
      (Coaches)" (#884) and declared as Files and docs in
      `docs/play/DATA_SAFETY.md`.
- [x] **Target API level**: `targetSdk = 36` and `compileSdk = 36` pinned
      explicitly in `mobile/android/app/build.gradle.kts` (minSdk stays 26),
      not relying on the Flutter default. Build toolchain (AGP 9.1.0 /
      Gradle 9.3.1 / Kotlin 2.4.0, Flutter 3.47.5 / Dart 3.13.4) supports
      SDK 36. Re-check Play's requirement on the submission date.
- [x] **Permissions review**: every merged-manifest permission justified in
      `docs/play/PERMISSIONS.md` (app: `INTERNET`, `ACCESS_NETWORK_STATE`,
      `CAMERA`, `RECEIVE_BOOT_COMPLETED`, `SCHEDULE_EXACT_ALARM`; plugins:
      `POST_NOTIFICATIONS` + `VIBRATE`, install-referrer binding). Exact
      alarms are kept for the rest timer (owner decision, 2026-11-17): the
      end-of-rest buzz is a user-set timer, the permission is asked once,
      Android 14+ denies it by default, and a refusal falls back to an
      inexact allow-while-idle alarm — the Play exact-alarm policy allows
      this for user-initiated timers.
- [x] **Store listing in EN and AR** prepared: `docs/play/STORE_LISTING.md`
      (name, short/full descriptions within Play length limits, AI
      disclosure, screenshot shot list, feature-graphic and icon notes per
      the `flutter_launcher_icons` pipeline). Screenshots and graphics
      themselves are owner work.
- [x] **No purchase path or Pro upsell on Android**: verified there is no
      purchase UI anywhere in the app (no buy/subscribe/upgrade buttons or
      links; Play Billing code does not exist yet — it arrives with #740).
      Pinned by `mobile/test/pro_purchase_gate_test.dart`, which runs the
      Lifter plan screen and the Settings screen on Android **and** on the
      default platform (the shared web/PWA code path) and asserts there is
      no purchase CTA and no external-URL launch. The one informational
      "AI roster questions require Coach Pro." text notice in the coach
      roster assistant panel is not a purchase path (no tap target, no link)
      and is left as-is. When #740 lands, gate any new purchase UI behind a
      **single** platform check and extend that test.
- [ ] Release build: signed AAB with a version-code bump, R8/obfuscation map
      uploaded, Sentry symbols if used. Owner work; commands in
      `docs/PLAY_RELEASE.md` §6.

## Rollout

Internal test → closed test (12+ testers, 14 days) → production application →
staged rollout (owner-driven; mirrors the issue).

## For the implementer of #749/#740 (and the #748 hand-off)

- **#748** ships in the same release as this ticket, so its public-policy
  section ("Assistant reply feedback and reports"), its Data safety row, and
  the listing's "report a reply" sentence are already prepared; its
  implementer only ships the feature code.
- **#749**: when it ships, update in the same release
  `docs/PRIVACY_POLICY.md` (add the new "Push notification tokens" section
  and bump `POLICY_VERSION` — the policy has no push wording today) and
  `docs/play/DATA_SAFETY.md` (remove the "planned" row and declare the
  tokens). This checklist too.
- **#740**: gate any new purchase UI behind a **single** platform check and
  extend `mobile/test/pro_purchase_gate_test.dart` (see the purchase-path
  bullet above).
