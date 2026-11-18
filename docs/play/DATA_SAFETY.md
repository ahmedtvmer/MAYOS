# Google Play Data safety form (answer key)

Prepared for issue #750. Answer key for Play Console → **App content → Data
safety**, derived from `docs/PRIVACY_POLICY.md` (version 1.13, effective
2026-11-17) and the closed-trial answer key in `docs/PLAY_RELEASE.md` §8. The
rule is unchanged: **the form may never contradict the published policy** —
Play rejects apps whose Data safety form and privacy policy disagree, so fill
the form only from what actually ships.

The owner submits this form; the implementer keeps this document in sync with
the policy and the code.

## Published privacy resources

| Resource | URL |
| :--- | :--- |
| Privacy policy (in Data safety form and App content) | `https://api.mayos.online/privacy` |
| Public account-deletion web page (linked from the landing site footer) | `https://mayos.online/account-deletion` |
| Direct deletion request form (the page above links here) | `https://api.mayos.online/account/delete-request` |

The `mayos.online` page exists so a user can request deletion **without having
the app installed**; it reuses the same rate-limited API endpoint as the form
above, with a `mailto:` fallback to `founders@mayos.online`. Use the
`mayos.online` page URL in Play's **Account deletion** fields (Play wants a
deletion page a user can reach without the app).

## Data types collected

| Play data type | Collected | Required / optional | Purpose | Shared with |
| :--- | :--- | :--- | :--- | :--- |
| **Personal info — username** | Yes | **Required** to create and use an account | App functionality (sign-in), account management | No one (processed by service providers only) |
| **Personal info — email address** (recovery email) | Yes | **Required**: the app blocks dashboard and onboarding until one is added (ADR 007 recovery gate) | App functionality (password recovery), account management | No one |
| **Health and fitness — body data**: weight, height, age, gender, body proportions, injuries/limitations free text | Yes | Optional — the Player chooses what to enter | App functionality (training) | No one |
| **Health and fitness — exercise history**: workouts, sets, weights, reps, effort (RIR/RPE), readiness, personal records, training schedule and pauses, check-ins | Yes | Optional — the Player chooses what to log | App functionality (training and coaching) | No one |
| **User content**: onboarding answers, assistant chat, program-request text | Yes | Optional | App functionality (onboarding uses deterministic rules; AI features use the hosted model provider) | No one |
| **User content — Assistant reply feedback and reports** (ships with #748 in the same release; policy section "Assistant reply feedback and reports"): the 👍/👎 vote or the Report action the Player takes on an assistant reply, stored with their account as the reply's message id and text, the question before it, the language and time, the assistant route or intent that answered, the model and prompt/graph version when available, the chosen reason codes (for example "Wrong information" or "Unsafe advice") and an optional bounded note | Yes | Optional — collected only when the Player votes or reports a reply | App functionality (AI quality); never used to train anything automatically | No one (report excerpts reach only the owner, through their Discord webhook, redacted so the post never includes the username, recovery email or account id) |
| **App activity — app interactions; Identifiers — user IDs**: pseudonymous feature events keyed by the immutable Account id | Yes | Automatic unless the Account's analytics is off, including preserved opt-outs and objections sent to the privacy contact | Analytics (feature use and product improvement) | PostHog (EU), service provider only |
| **App info and performance — Crash logs** (release builds): error message and stack trace, app/service release and platform, breadcrumbs reduced to screen names (ids placeholdered) and HTTP method/route template/status | Yes | Automatic in release builds only | App functionality (stability and debugging) | Sentry (EU), service provider only |

Notes on the crash-logs row (policy: "Error reporting (Sentry)"):

- The account attached to a report is identified only by a **pseudonymous,
  one-way-hashed account id** (`svc/error_tracking.py::anonymous_account_id`);
  no username, recovery email or raw account id is included.
- IP addresses are **not stored** (`sendDefaultPii = false`, IP set to
  `0.0.0.0`); screenshots, view hierarchies and session replays are disabled.
- Reports never contain chat text, onboarding answers, workout contents,
  program requests or contact details.
- Debug and profile builds do not report to Sentry.

Also collected but not a Play data-type row: the **Play install referrer is
read once per install** and only parsed UTM labels (source/medium/campaign)
are sent with registration (see `docs/PLAY_RELEASE.md` §8). No advertising ID,
no device identifier, no contacts, no location, no microphone audio, no
photos/video of the person: the camera is used only to capture a photo the
Player themselves adds to a locally generated workout share card, and that
photo stays on the device (it is never uploaded).

## Form questions

| Play question | Answer |
| :--- | :--- |
| Data collected | The types in the table above: username, recovery email, health/fitness data, user content (including assistant reply feedback and reports), pseudonymous app interactions, crash logs, and internal Account ids. No contacts, no location, no device identifiers, no advertising IDs |
| Data shared | **No data sold, no data shared for advertising, no tracking.** Data *is* processed by service providers: the hosted model provider (AI features, DeepInfra by default), the SMTP provider (emails), PostHog EU (product analytics), and Sentry EU (crash reporting) |
| Data processed securely | Yes — encrypted **in transit** (https/TLS) |
| Data deletion available | **Yes**, both in-app (Settings → Linked sign-in → Danger zone → Delete account) and on the web (`https://mayos.online/account-deletion`, which links the direct request form) |
| Required or optional | **Username and recovery email are required**; training, health, AI content, and reply votes/reports are optional; logs, analytics, and crash reports are collected automatically (existing analytics opt-outs remain off permanently) |
| Purpose | App functionality, account management, security, AI features and reply feedback quality, product analytics (PostHog EU), and crash reporting (Sentry EU); no advertising or third-party product improvement |
| Independent verification | No |

Deleting the account removes assistant reply feedback and reports with it,
exactly as the policy's "Deleting your account" section states.

## Planned feature — do NOT declare until it ships

One feature is planned for before the Play launch but is **not implemented
yet**. The Data safety form must reflect what the uploaded build actually
does, so its rows are added **only together with the release that ships it**
(and with the matching privacy-policy section):

- **Push notification tokens** (issue #749, not yet shipped): FCM device
  tokens (or Web Push subscription endpoints) plus per-device notification
  settings and server-side delivery state. Declare as **App activity — App
  interactions** (or App info and performance, per Play's picker at
  submission time), purpose "Messaging (app functionality)", processed via
  **Google's FCM** as a delivery processor. #749 must also **add the
  "Push notification tokens" section to `docs/PRIVACY_POLICY.md`** — the
  public policy deliberately has no push/FCM wording today, because the app
  sends no push notifications until #749 ships.

When it ships, update this document, `docs/PRIVACY_POLICY.md` (add the
matching section and bump `POLICY_VERSION`), and the Data safety form in the
same release.

**Assistant reply feedback and reports (#748) is NOT in this list**: it ships
in the same release as this ticket, ahead of it, so its row is already in the
"Data types collected" table above and must be declared with the first
submission.

## Related declarations

- **Health apps declaration / fitness category**: MAYOS stores self-reported
  fitness data (body data and exercise history above). Declare the app in the
  **Health & Fitness** category and complete the Health apps declaration
  stating the app collects user-entered fitness data and stores it (not a
  fitness-record-sharing service, no third-party health-data exchange).
- **Content rating**: fitness/training app, health-adjacent self-reported
  data, no violence, no user-to-user messaging (AI chat is assistant-to-user
  only; coaches never see player chats).
- **Target audience**: 16+, not designed for families (matches the policy's
  children statement).
