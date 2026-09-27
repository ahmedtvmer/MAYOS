# #54 — Visual verification: MAYOS Android redesign

Final cross-screen verification for the Android player redesign (parent #47).
This pass captured every shipped player surface across the two target phone
sizes, both explicit themes, System theme, and 2.0× text scaling; fixed the
cross-screen inconsistencies it surfaced; and recorded the result below.

## How these captures were produced

```bash
cd mobile
CAPTURE=1 flutter test --tags capture --plain-name '54 ' test/visual/capture_test.dart
```

The harness renders with the bundled fonts and Material icon font loaded, at a
2.0 device pixel ratio, and writes PNGs to `docs/design-review/54/`. Sizes are
`360x640` (small) and `412x915` (common). Themes are `light`, `dark`, and
`system`. System-theme fixtures override the platform brightness in the harness.

The companion non-tagged suites (run by `flutter test`) exercise the same
surfaces at 2.0× text in both themes and assert no overflow or layout exception:

- `mobile/test/design_review_54_test.dart` — offline Home, chart ticks/edge
  padding, and the 2.0× / both-theme sweep of every captured screen.
- The existing widget suites still cover the functional flows (logger save,
  drafts edit/retry/discard, chat send/retry, account-deletion dialog).

## Capture index

Each cell links to the PNG. Light/Dark columns are the 360×640 capture; the
412×915 variant is the same file name with `412x915`.

| Screen | Light | Dark | Small/notes |
| --- | --- | --- | --- |
| Splash | [splash-light-360x640](splash-light-360x640.png) | [splash-dark-360x640](splash-dark-360x640.png) | logo lockup hero |
| Login | [auth-login-light-360x640](auth-login-light-360x640.png) | [auth-login-dark-360x640](auth-login-dark-360x640.png) | + [text-scale 2.0](auth-login-light-360x640-textscale2.png) |
| Register | [auth-register-light-360x640](auth-register-light-360x640.png) | [auth-register-dark-360x640](auth-register-dark-360x640.png) | |
| Recovery-email gate | [auth-recovery-email-light-360x640](auth-recovery-email-light-360x640.png) | [auth-recovery-email-dark-360x640](auth-recovery-email-dark-360x640.png) | |
| Onboarding — disclosure | [onboarding-disclosure-light-360x640](onboarding-disclosure-light-360x640.png) | [onboarding-disclosure-dark-360x640](onboarding-disclosure-dark-360x640.png) | |
| Onboarding — specialization | [onboarding-specialization-light-360x640](onboarding-specialization-light-360x640.png) | [onboarding-specialization-dark-360x640](onboarding-specialization-dark-360x640.png) | plain-language option copy |
| Onboarding — proportions | [onboarding-proportions-light-360x640](onboarding-proportions-light-360x640.png) | [onboarding-proportions-dark-360x640](onboarding-proportions-dark-360x640.png) | + [text-scale 2.0](onboarding-proportions-light-360x640-textscale2.png) |
| Onboarding — numeric step | [onboarding-numeric-light-360x640](onboarding-numeric-light-360x640.png) | [onboarding-numeric-dark-360x640](onboarding-numeric-dark-360x640.png) | |
| Onboarding — review | [onboarding-review-light-360x640](onboarding-review-light-360x640.png) | [onboarding-review-dark-360x640](onboarding-review-dark-360x640.png) | |
| Home | [home-light-360x640](home-light-360x640.png) | [home-dark-360x640](home-dark-360x640.png) | + [text-scale 2.0](home-light-360x640-textscale2.png), offline fallback |
| Program | [program-light-360x640](program-light-360x640.png) | [program-dark-360x640](program-dark-360x640.png) | |
| Exercise detail | [exercise-detail-light-360x640](exercise-detail-light-360x640.png) | [exercise-detail-dark-360x640](exercise-detail-dark-360x640.png) | |
| Progress (Strength) | [progress-strength-light-360x640](progress-strength-light-360x640.png) | [progress-strength-dark-360x640](progress-strength-dark-360x640.png) | rounded ticks, edge marker |
| Settings | [settings-light-360x640](settings-light-360x640.png) | [settings-dark-360x640](settings-dark-360x640.png) | + [text-scale 2.0](settings-light-360x640-textscale2.png) |
| Settings — System | — | [settings-system-dark-360x640](settings-system-dark-360x640.png) | [settings-system-light-360x640](settings-system-light-360x640.png) |
| Assistant chat | [chat-light-360x640](chat-light-360x640.png) | [chat-dark-360x640](chat-dark-360x640.png) | MAYOS bubbles, no generic AI look |
| Workout logger | [workout-logger-light-360x640](workout-logger-light-360x640.png) | [workout-logger-dark-360x640](workout-logger-dark-360x640.png) | dense, legible numeric cells |
| Workout drafts | [workout-drafts-light-360x640](workout-drafts-light-360x640.png) | [workout-drafts-dark-360x640](workout-drafts-dark-360x640.png) | one pending draft |

The 412×915 variant of each screen exists under the same name with the
`412x915` suffix (for example `home-dark-412x915.png`).

## AC2 checklist

Result key: **pass** (verified, no change needed) · **fixed** (issue found and
corrected in this ticket) · **limitation** (documented, not a regression).

| # | Item | Result | Evidence / notes |
| --- | --- | --- | --- |
| 1 | Supplied logo legibility | pass | Mark-only crop + letterspaced `MAYOS` wordmark in the header; coloured lockup on splash. Blue-on-light excluded per `mobile/DESIGN.md`. |
| 2 | Typography | pass | One serif/sans pair via `MayosTypography`; no screen sets a font family or literal `TextStyle`. |
| 3 | Spacing & visual hierarchy | fixed | Literal `EdgeInsets.all(16/24)` and ad-hoc `SizedBox` values replaced with `MayosSpacing` across profile, plan, assignment, drafts, logger, chat and coach screens. |
| 4 | Touch targets (≥48dp) | fixed | Router sub-pages now use `MayosScaffold` (48dp back), set-row icon actions and all `MayosButton` variants keep the 48dp minimum; drafts actions are `IconButton`s. |
| 5 | Focus order | pass | Auth/onboarding forms keep declaration order; `MayosTextField` passes focus through unchanged. |
| 6 | Text scaling | fixed | Sweep at 2.0× found real overflows: profile dropdown (right, 94px), drafts summary Row (bottom, 127px), chat disclosure card (bottom, 1216px) and a chat header Row. All fixed; `design_review_54_test.dart` now asserts no overflow for every captured screen in both themes. |
| 7 | Keyboard behaviour | pass | Auth screens keep the pinned action bar + `resizeToAvoidBottomInset`; login keyboard inset capture unchanged since #52. |
| 8 | Loading / error / empty states | pass | Home skeleton/error, Program offline banner, Progress empty state, chat disclosure/offline/error, drafts empty/pending/attention, plan/coach empties — all use shared styling. |
| 9 | System-bar contrast | pass | `MayosApp` wraps every route in `AnnotatedRegion<SystemUiOverlayStyle>` from the effective theme; `theme_and_shell_test` asserts icon brightness per theme. Splash/onboarding/auth render inside the same app wrapper. |

## One-off styling fixed in this ticket

Shared system:

- `MayosButton`: added a `destructive` variant (danger fill) used by account
  deletion, so destructive actions stop hand-rolling `FilledButton.styleFrom`.
- `MayosTextField`: added `dense` (narrow workout-set cells), `minLines` and
  `autofocus` passthroughs so screens stop dropping to raw `TextField`.
- `router.dart`: replaced eight `Scaffold(appBar: AppBar(...))` wrappers
  (Plan, Profile, Coach, Assignments, Alerts, Coaching, Workouts, Log workout)
  with `MayosScaffold` + `MayosAppHeader`.

Per screen:

- **Chat** — `MayosScaffold`; MAYOS token bubbles (accent user / secondary
  assistant, not `ColorScheme` containers); `MayosCard` disclosure; token
  offline/error banners; `MayosTextField` composer; gate made scrollable.
- **Workout logger** — tokens + `MayosTypography`; `MayosCard` per exercise;
  `MayosSettingsTile` date row; `MayosSectionHeader` readiness; `MayosButton`;
  dense `MayosTextField` set cells (kg/reps/RPE labels and values now legible at
  360dp); shared offline notice; token danger text. Behaviour unchanged.
- **Workout drafts** — `MayosCard`/`MayosButton`/tokens; summary uses a `Wrap`
  so it reflows at large text instead of overflowing.
- **Profile** — tokens + `MayosSectionHeader`/`MayosTextField`/`MayosButton`;
  destructive delete button; deletion dialog uses `MayosButton`/`MayosTextField`;
  dropdowns `isExpanded` to survive large text.
- **Plan** — `MayosCard`/`MayosSectionHeader`/tokens.
- **Coaching assignment** — `MayosCard`/`MayosButton`/`MayosTextField`/tokens;
  request and end dialogs use shared buttons.
- **Coach profile / invite / alerts / roster** — tokens, `MayosCard`,
  `MayosButton`, `MayosSettingsTile`; invite moved to `MayosScaffold`.
- **Coach player history** — token danger colours and `MayosSpacing`; retains
  themed Material `Card`/`ListTile` (owned by the coach drill-down ticket #25).

## Known limitations

- **Fonts are approximations.** Playfair Display / Inter stand in for the
  reference faces; recorded in `mobile/DESIGN.md`.
- **Raster logos.** The bundled marks are derived crops of the supplied PNGs;
  the header uses the documented clean text treatment because the baked wordmark
  is illegible at ~30dp. Blue-on-light stays excluded.
- **Exercise media stays off.** ExerciseDB-derived imagery has undocumented
  provenance, so exercise detail ships the no-image layout with placeholders
  (prompt §21). No file paths were invented.
- **System-theme captures** demonstrate the behaviour with the platform
  brightness overridden by the harness (a widget test has no OS setting).
- **Text-scale 2.0 capture set** covers the four highest-risk screens (Home,
  onboarding proportions, login, Settings); overflow at 2.0× is additionally
  asserted for every captured screen by `design_review_54_test.dart`.
- **Coach drill-down** visual treatment is at token level only; a full restyle
  belongs with #25 if it is revisited.

## #49 non-negotiable checklist (status)

- [x] MAYOS remains a Flutter mobile app.
- [x] The attached UI reference has been inspected.
- [x] Supplied logo variants used where legible, without changing proportions.
- [x] Licensed serif/sans typography centralized and documented as an approximation.
- [x] Dark mode fully implemented.
- [x] Light mode fully implemented.
- [x] System/Light/Dark choice works and persists on device.
- [x] No major screen ignores the current theme.
- [x] Onboarding no longer resembles chat.
- [x] Major onboarding questions use focused full-screen steps.
- [x] Structured answers save to the account and remain editable before creation.
- [x] Existing incomplete intake answers prefill the new screens where available.
- [x] Hosted-processing disclosure appears before relevant data is sent.
- [x] Body proportions has three premium visual selections.
- [x] The onboarding experience feels designed, not form-generated.
- [x] Main navigation is truly mobile (Home · Program · Progress).
- [x] Home labels the unscheduled program day “Next session.”
- [x] Read-only exercise details use real program data and work without imagery.
- [x] No unsupported readiness score, chart, workout action, or dead-end destination.
- [x] Existing business/domain behaviour remains intact (backend `pytest` green).
- [x] Design tokens are centralized.
- [x] Hard-coded random colors are eliminated outside `core/theme/`.
- [x] The app does not look like Hevy.
- [x] The app does not look like a generic AI product (chat included).
- [x] Light mode is not an afterthought.
- [x] UI works on realistic phone dimensions (360×640 and 412×915).
- [x] No obvious overflow/layout errors remain (sweep at 2.0× text).
- [x] Existing tests still pass; new #54 widget tests added.
- [x] Static analysis passes (`flutter analyze` clean).
- [x] Dead UI code from the previous implementation removed where safe.
