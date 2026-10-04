# Product analytics tracking plan

Product analytics uses PostHog EU cloud for behavior, funnels, retention, cohorts,
and adoption. The registry and Training ledger remain authoritative for account,
training, roster, and financial facts. Analytics is observational: events are
captured after their domain writes commit, and provider failures never fail an
operation. There is no transactional outbox, so a process crash between commit
and capture can lose an event.

## Identity and privacy

- PostHog `distinct_id` is the immutable Account id. It is never a username,
  email, token, or client identifier.
- The registry stores each Account's analytics preference, allowed by default.
  Opting out suppresses that Account's server events and person updates at the
  analytics boundary, and disables the Flutter client for that Account. The
  sole exception is one best-effort person update after the preference change
  commits. If the registry preference cannot be read, the service suppresses
  the send. A deleted Account is also denied by the gate even after its
  preference row has been removed.
- The gate follows an event or person update's `distinct_id`. An opted-out
  Account's own events and person updates are suppressed. A counterpart's event
  can still be sent when that Account allows analytics; for example, an
  `assignment_started` event from an opted-out Player redeeming an invite is
  attributed to the Coach. That event does not identify the opted-out Player.
- Mutable person properties are `is_player`, `is_coach`, `coached`,
  `active_roster_size`, and `analytics_opted_out`. The initial `signup_phase` is set once from
  `MAYOS_RELEASE_PHASE` (`closed_trial` by default; `public` after launch).
  UTM and referrer properties are set once at registration; referral Coach
  attribution is set once after the first successful Assignment invite redemption.
- Every event carries `role`, `platform`, `app_version`, and `env`.
  `X-MAYOS-Client` uses `platform/version` (for example, `android/1.2.3`);
  missing or invalid headers resolve to `unknown`. The service owns that
  resolution in one helper so the client-header implementation can extend it.
- `env` uses one of `development`, `production`, or `test` from `MAYOS_ENV`;
  the default is `development`. Fly sets `MAYOS_ENV=production` explicitly.
  `TESTING=1` or no `POSTHOG_API_KEY` disables sends.
  `POSTHOG_HOST` can override the default EU endpoint
  (`https://eu.i.posthog.com`).
- Before configuring either key, turn on **Discard client IP data** in each
  PostHog project that receives server or Flutter events. The server SDK's
  `disable_geoip` and client `$geoip_disable` property suppress GeoIP enrichment,
  but do not prevent PostHog from storing `$ip`; the project setting must be on
  before either key is used. The web SDK also sets `ip: false`; the Flutter
  native SDK has no per-request IP discard option and sets `$geoip_disable`.
- The Flutter PostHog client is enabled only in release builds when the public
  project key is supplied as `--dart-define=POSTHOG_CLIENT_KEY=...`. Android
  and web use `https://eu.i.posthog.com`. Debug and profile builds, and builds
  without the define, use a no-op client. The key is used only by release
  builds; passing it to `flutter run` has no effect unless `--release` is used.
  The app registers
  `$geoip_disable` with PostHog. Autocapture, heatmaps, dead clicks, exceptions,
  performance capture, surveys, rage clicks, page views, lifecycle events,
  screen views, session replay, and push-notification capture are disabled.
- The adapter disables exception autocapture and logs no captured exceptions;
  GeoIP enrichment is disabled. Events never contain usernames, emails, passwords, tokens, IP
  addresses, free text, onboarding answers, prompts, completions, or workout
  contents.
- Account deletion removes `first_touch_acquisition` and
  `account_analytics_preferences` in the registry teardown transaction. After
  that transaction commits, the service makes a best-effort PostHog deletion
  request by immutable `distinct_id`, including prior events. PostHog processes
  event removal asynchronously ([PostHog persons API](https://posthog.com/docs/api/persons)).
  The durable `account_deletions` row remains pending until a successful
  request made at least one hour after `deleted_at`; an immediate request is
  best-effort and cannot mark the row delivered. After that grace period, a
  successful 2xx response, including `persons_found == 0`, marks it delivered
  and it is not repeated. Requests use `POSTHOG_PERSONAL_API_KEY` (scoped only
  to `person:write` for the MAYOS project), `POSTHOG_PROJECT_ID`, and
  `POSTHOG_API_HOST` (defaults to `https://eu.posthog.com`), with a two-second
  timeout. Missing deletion credentials or a no-op sink leave the record
  pending without incrementing attempts; the hourly sweep skips deletion work
  entirely when credentials are absent. Provider errors leave the record
  pending. Each sweep retries at most 100 mature records, ordered by attempt
  count and then oldest last attempt so repeated failures do not starve newer
  deletions. These failures never undo account deletion. Events about the
  deleted Account itself are suppressed by the live-account gate, while an
  allowed surviving Coach's or Player's `assignment_ended` event still sends.
  Historical events attributed to a surviving Player retain the deleted
  Coach's opaque `coach_id` property; deleting the Coach person does not rewrite
  another Account's event properties.
- Event UUIDs are UUID5 values derived from the event name and its domain key.
  Assignment events use the assignment or invite identity; Coach capability
  transitions use the Account id and committed timestamp; failed redemption
  events use one generated attempt identity.
  Account-scoped events use the immutable account id; program events use the
  program version (or assignment publication) and request events use the
  request id plus its transition.
- The code catalogue and current server events are contract-tested for exact
  name parity. The strict recording sink rejects unknown events, extra or
  missing properties, and values outside each property's safe type or
  vocabulary. The production adapter drops and logs contract violations.

## First-touch acquisition

Registration accepts an optional `first_touch` object on password registration
and Google signup completion. Web writes its first UTM/referrer snapshot to
browser storage only when no earlier snapshot exists, preserving it across
refreshes, the splash-to-login redirect, and return visits until registration;
it clears that snapshot after a successful registration. Android persists the
parsed Play Install Referrer result or an empty-read marker, so the plugin is
called at most once per install. The app does not read it for a signed-in
account. Web captures `utm_source`, `utm_medium`, and `utm_campaign` from the
initial URL plus only the host of `document.referrer`.

The Android device parses the install-referrer query string locally and sends
only its three UTM labels; click identifiers and other query parameters never
reach the service.

The registry stores one row in `first_touch_acquisition` with the normalized
UTM labels and `referrer_host`. It is inserted in the Account creation
transaction and cannot be changed, except to attach the first redeemed
Assignment's Coach id and `referred_at`. Person properties use PostHog's
set-once operation for the same populated fields. The
service lowercases UTM labels, accepts at most 64 characters from
`[a-z0-9._-]`, and drops a label that does not meet that rule. It extracts and
stores only the hostname from a referrer; URL paths, query strings, and
credentials are discarded. The install referrer is parsed and discarded: click
identifiers and all non-UTM parameters are not stored or sent to PostHog.

On the first successful Assignment invite redemption, the registry sets
`referring_coach_id` to the opaque Account id of the Coach whose invite the
account redeemed first, with `referred_at` in the same redemption transaction.
That value can move only from NULL to its first Coach id and is mirrored to the
PostHog person with a set-once update after commit.

Channel names are not stored in the app or registry. PostHog and BI apply an
editable classification with this precedence: a `referring_coach_id` is a
Coach referral; otherwise a recognized `utm_medium` mapping determines the
channel, with `utm_source` and `utm_campaign` used for breakdowns; otherwise a
known `referrer_host` mapping determines the referrer channel; with no signal,
classify as direct or unknown. Unknown UTM labels remain available as raw,
normalized values so the PostHog/BI mapping can change without rewriting the
registry.

## Current event catalogue

<!-- event-catalogue:start -->
| Event | Origin | Trigger | Properties |
|---|---|---|---|
| `account_created` | server | A password or Google registration has committed and its account ledger is ready. | `role`, `platform`, `app_version`, `env`, `signup_phase`, `invite_used` |
| `coach_capability_granted` | server | A Coach invite redemption has committed and granted Coach capability. | `role`, `platform`, `app_version`, `env` |
| `coach_capability_disabled` | server | A Coach has explicitly disabled Coach capability after any active Assignments end. | `role`, `platform`, `app_version`, `env` |
| `onboarding_started` | server | The first committed onboarding write: disclosure, first named answer, or legacy start/answer. Reads do not create this event. | `role`, `platform`, `app_version`, `env` |
| `onboarding_completed` | server | The first successful onboarding completion has committed and its completion time is persisted. Retries and replayed confirmation do not create another event. | `role`, `platform`, `app_version`, `env`, `duration_seconds`, `prefilled_fields_count` |
| `onboarding_step_viewed` | client | A Player is shown one onboarding step. Sent on each display of that step; answer values are excluded. | `role`, `platform`, `app_version`, `env`, `step` |
| `assignment_invite_issued` | server | A Coach's single-use Assignment invite has been stored. | `role`, `platform`, `app_version`, `env`, `active_roster_size` |
| `assignment_started` | server | A Player has consented and the invite claim and active Assignment have committed; the Coach (roster owner) is the distinct id. | `role`, `platform`, `app_version`, `env`, `coach_id`, `active_roster_size`, `time_since_invite_seconds` |
| `assignment_ended` | server | An active Assignment has ended through either participant, Coach disablement, or account deletion; the Coach (roster owner) is the distinct id unless that Coach was deleted, in which case it is the surviving Player. | `role`, `platform`, `app_version`, `env`, `ended_by`, `duration_seconds`, `active_roster_size` |
| `invite_redemption_failed` | server | A Player's Assignment invite redemption was refused. | `role`, `platform`, `app_version`, `env`, `reason_code` |
| `program_generated` | server | A program version is created during onboarding, a profile rebuild, a player request, a coach split-change apply, or lazy synthesis on the active-program read. | `role`, `platform`, `app_version`, `env`, `trigger`, `day_count` |
| `coach_program_published` | server | A Coach publishes a program to an active Assignment after the program version commits. Coaching action. | `role`, `platform`, `app_version`, `env`, `day_count`, `first_for_assignment`, `is_coaching_action` |
| `program_exercise_swapped` | server | A Player swaps or undoes an exercise swap, or a Coach applies an exercise-substitution request after the new program version commits. The `role` identifies who acted. | `role`, `platform`, `app_version`, `env` |
| `program_request_created` | server | A Player's program request has committed to the registry. | `role`, `platform`, `app_version`, `env`, `kind` |
| `program_request_resolved` | server | A Coach applies or declines a request, or a Player cancels it, after the registry transition commits. Coach resolutions are coaching actions. | `role`, `platform`, `app_version`, `env`, `outcome`, `time_open_seconds`, `is_coaching_action` |
| `workout_completed` | server | A workout commit has succeeded. An idempotent replay emits nothing; the client session id determines the event UUID when present, with the committed session id as the fallback. | `role`, `platform`, `app_version`, `env`, `set_count`, `exercise_count`, `load_complete_set_count`, `reps_complete_set_count`, `rir_complete_set_count`, `divergence_count`, `unplanned_exercise_count`, `captured_offline`, `sync_delay_seconds`, `is_first_workout`, `program_provenance`, `coached` |
| `performed_date_corrected` | server | A committed workout's performed date has changed and the correction row is stored. A no-op correction emits nothing. | `role`, `platform`, `app_version`, `env` |
| `training_schedule_set` | server | A new Training schedule version has committed. | `role`, `platform`, `app_version`, `env`, `days_per_week` |
| `schedule_pause_scheduled` | server | A prospective Training schedule pause has committed. | `role`, `platform`, `app_version`, `env`, `length_days` |
| `workout_sync_failed` | server | The authenticated client reports a failed Workout draft sync attempt. | `role`, `platform`, `app_version`, `env`, `sync_failure_reason`, `attempt` |
| `workout_started` | client | A new Active workout is saved locally before logger navigation; resuming an existing Active workout is not a new start. | `role`, `platform`, `app_version`, `env` |
| `workout_draft_discarded` | client | A Player explicitly discards an Active workout or an unsynced Workout draft. The client deduplicates by local workout identity and sends no workout identifier. | `role`, `platform`, `app_version`, `env` |
<!-- event-catalogue:end -->

### Property definitions

| Property | Type and allowed values | Meaning |
|---|---|---|
| `is_player` | Boolean person property | The Account has Player capability. |
| `is_coach` | Boolean person property | The Account has Coach capability. |
| `coached` | Boolean person property | The Player has an active Assignment. |
| `active_roster_size` | Integer from 0 to 200; person property and assignment event property | The Coach's count of active Assignments, read from committed registry state. |
| `analytics_opted_out` | Boolean person property | Whether the Account holder turned product analytics off. Updated once after the preference change commits. |
| `role` | `player`, `coach`, or `unknown` | Capability for the event's distinct id; Assignment lifecycle events describe the roster owner except when the Coach is deleted. |
| `platform` | `android`, `web`, or `unknown` | Flutter client platform; server events use `X-MAYOS-Client`. |
| `app_version` | Safe version label or `unknown` | Flutter build name; server events use `X-MAYOS-Client`. |
| `env` | `development`, `production`, or `test` | Release Flutter events use `production`; server uses `MAYOS_ENV`, defaulting to `development`. |
| `signup_phase` | `closed_trial` or `public` | Release phase at account creation; also set once on the person. |
| `utm_source` | Lowercase `[a-z0-9._-]`, 1–64 characters | First-touch source label; set once on the person and stored in `first_touch_acquisition`. |
| `utm_medium` | Lowercase `[a-z0-9._-]`, 1–64 characters | First-touch medium label; set once on the person and stored in `first_touch_acquisition`. |
| `utm_campaign` | Lowercase `[a-z0-9._-]`, 1–64 characters | First-touch campaign label; set once on the person and stored in `first_touch_acquisition`. |
| `referrer_host` | Lowercase hostname, up to 253 characters | Host extracted from the first web document referrer; paths and query strings are discarded. |
| `referring_coach_id` | Immutable Account UUID | Opaque Account id of the Coach whose Assignment invite the account redeemed first; set once after account creation. |
| `invite_used` | Boolean | Whether registration consumed a new-account Coach invite. No invite code is sent. |
| `duration_seconds` | Bounded nonnegative integer | For onboarding, elapsed whole seconds from the first persisted start to completion; for an Assignment, elapsed whole seconds from its committed start to end. |
| `coach_id` | Immutable Account UUID | Opaque id of the Coach on an `assignment_started` event. |
| `time_since_invite_seconds` | Bounded nonnegative integer | Elapsed whole seconds from Assignment invite creation to committed redemption. |
| `ended_by` | `player`, `coach`, `coach_capability_disabled`, or `account_deleted` | Who or what ended the Assignment. |
| `reason_code` | `unknown_code`, `already_redeemed`, `expired`, `coach_unavailable`, `not_a_player`, `self_assignment`, `already_assigned`, `capacity`, or `consent_required` | Coded reason for a refused Assignment invite redemption; a same-Player retry after a successful redemption is `already_redeemed`. The HTTP error remains generic for unknown, redeemed, expired, unavailable-Coach, and non-Player cases. No token or free text is sent. |
| `prefilled_fields_count` | Integer from 0 to 100 | Number of legacy-prefilled answers at completion. Answer values are never sent. |
| `step` | Allowlisted onboarding step identifier | One of `disclosure`, each field in `service/intake.py::INTAKE_FIELDS`, or `review`. No answer values are sent. |
| `trigger` | `onboarding`, `profile_rebuild`, `player_request`, `synthesized`, or `coach_request` | Why a program version was generated. |
| `day_count` | Integer from 0 to 100 | Number of days in the saved program. Program names and exercise names are never sent. |
| `first_for_assignment` | Boolean | Whether this is the first coach publication since the active Assignment began. |
| `is_coaching_action` | Boolean | True for a recorded coaching action. Coach publication and request resolution by a Coach are true; Player cancellation is false. |
| `kind` | `exercise_substitution` or `split_change` | Program request category. Request reason and split preference are never sent. |
| `outcome` | `applied`, `declined`, or `cancelled` | Program request's committed resolution. A decline response is never sent. |
| `time_open_seconds` | Bounded nonnegative integer | Whole seconds between request creation and resolution, capped at one year. |
| `set_count` | Integer from 0 to 1000 | Number of logged working sets, capped at 1000; Warm-up sets are excluded. |
| `exercise_count` | Integer from 0 to 100 | Number of distinct exercises with a logged working set, capped at 100. Exercise ids and names are never sent. |
| `load_complete_set_count` | Integer from 0 to 1000 | Working sets with a recorded load, capped at 1000. The load values are never sent. |
| `reps_complete_set_count` | Integer from 0 to 1000 | Working sets with a recorded rep count, capped at 1000. The rep values are never sent. |
| `rir_complete_set_count` | Integer from 0 to 1000 | Working sets with an effort rating from which RIR is available, capped at 1000; the rating and RIR values are never sent. |
| `divergence_count` | Integer from 0 to 100 | Skipped plus unplanned exercise divergences recorded at commit, capped at 100. Exercise ids and names are never sent. |
| `unplanned_exercise_count` | Integer from 0 to 100 | Unplanned exercises among the committed divergences, capped at 100. |
| `captured_offline` | Boolean | The client sets this when the workout is finished without connectivity or a sync status lookup/commit fails because connectivity is unavailable. It persists on the Workout draft and is sent on the eventual commit; platform and client-session presence do not imply offline capture. |
| `sync_delay_seconds` | Integer from 0 to 31,557,600 | Whole seconds from the Workout draft capture instant to its successful commit when `captured_offline` is true; otherwise zero, capped at the catalogue bound. |
| `is_first_workout` | Boolean | True when this is the Player's first completed workout recorded in MAYOS. Imported history is excluded. |
| `program_provenance` | `generated`, `coach_published`, or `none` | Whether the program used for the workout was generated, published by a Coach, or absent. Program and Coach ids are never sent. |
| `days_per_week` | Integer from 0 to 7 | Number of weekdays in the newly committed Training schedule. Weekday identities are not sent. |
| `length_days` | Integer from 1 to 14 | Inclusive length of a committed prospective Training schedule pause. Dates and reason text are never sent. |
| `attempt` | Integer from 1 to 100 | Bounded sync attempt number reported by the client. |
| `sync_failure_reason` | `network`, `server`, `conflict`, or `rejected` | Coded reason for a failed Workout draft sync. No response text or workout identifier is sent. |

## PostHog and operational database boundary

PostHog is for product behavior, funnels, retention, cohorts, and adoption. The
registry and Training ledger remain the source for account state, assignments,
rosters, completed workouts, and acquisition or financial records. Revenue,
MRR, payment reconciliation, contribution margin, and infrastructure cost are
not reconstructed from analytics events.

The service uses the PostHog SDK's background queue for events. It sends no
events without a project key and never sends from test mode. Person deletion is
exposed by the MAYOS analytics interface and uses PostHog's private persons API;
the deletion request is independent of coaching relationship events.

## Privacy-notice draft — Draft — awaiting owner approval

MAYOS uses PostHog (EU) as a product-analytics processor. MAYOS sends
pseudonymous events associated with an immutable Account id to measure feature
use, such as onboarding, workouts, coaching, programs, and AI. Events use
allowlisted properties such as event names, capabilities, counts, and timing
metadata; they do not contain free text, chat messages, onboarding answers,
prompts, or workout contents. Account
holders can turn product analytics off in Settings. When analytics is off,
MAYOS stops sending that Account's own server and Flutter client analytics
events. Events attributed to a counterpart remain subject to that counterpart's
choice and do not identify the opted-out Account. The choice is stored with the
Account and applies again after signing in on another session.
