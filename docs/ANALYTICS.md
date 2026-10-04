# Product analytics tracking plan

Product analytics uses PostHog EU cloud for behavior, funnels, retention, cohorts,
and adoption. The registry and Training ledger remain authoritative for account,
training, roster, and financial facts. Analytics is observational: events are
captured after their domain writes commit, and provider failures never fail an
operation. There is no transactional outbox, so a process crash between commit
and capture can lose an event.

## Setup

Keys, PostHog project settings and the release-build defines are set up in
[DEPLOYMENT.md, section 12](DEPLOYMENT.md#12-product-analytics-posthog-setup).

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
  the version must be a three-part numeric version with optional prerelease or
  build labels. Missing or invalid versions resolve to `unknown`; a bad version
  does not invalidate an otherwise recognized platform.
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
- Coach alert events include only the alert kind and bounded time-open duration;
  check-in events include only the coaching-action flag and are emitted as soon
  as the check-in row commits, before follow-up reconciliation. Check-in notes,
  alert explanations, Player ids, and Assignment ids are never event properties.
- Coach alert and Player history views have catalog-side daily deduplication
  markers. The hourly sweep prunes markers older than 30 days, and account
  deletion removes markers owned by the deleted Coach or tied to their
  Assignments. System-resolved alerts do not emit `coach_alert_resolved`; that
  event records only a Coach's committed resolution. A resolution reason is
  reserved for a future `not_useful` value and is not currently sent.
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

## Final privacy review

Sent: the immutable Account UUID as distinct_id; fixed event names; the typed
role, platform, version and environment dimensions; bounded counts and durations;
allowlisted categories; and first-touch UTM labels/referrer host set once on the
person. AI usage uses aggregate token and cost counts, not credentials or text.

Never sent: Account usernames or names, recovery emails, passwords, auth or
invite tokens, IP addresses, chat or assistant text, prompts or completions,
onboarding answers, check-in notes, program/request text, exercise names,
individual workout values, payment credentials, provider references, or
counterpart Account ids. First-touch labels accept only bounded normalized
characters; email/handle syntax, free text, JWT-like long tokens and IP literals
are rejected. IP capture and GeoIP enrichment are disabled at the provider.

The automated privacy review in tests/test_analytics.py checks every property
type used by the event and person catalogues against representative free text,
an email, a username-style handle, a JWT-like token, IPv4 and IPv6 values. It
also rejects sensitive property names while allowing bounded aggregate AI token
counts. Referrer and UTM validators reject canonical and legacy IPv4 forms plus
IPv6 literals before data reaches the catalogue.

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
`[a-z0-9._-]`, drops a label that does not meet that rule, and rejects IP
literals before storage or capture. It extracts and
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

## Implemented and planned event contracts

The code catalogue validates only rows marked implemented. Planned rows are
explicit contracts for tickets that will add those systems; they are not
accepted event names yet. Implemented events have a closed property set, so all
listed properties are required and no optional properties are accepted. Every
server event is captured after its authoritative write commits, except coded
failure or refusal events whose source is the authoritative request outcome.
Every client event is emitted only for the named local UI action.

The planned contract uses the prices and limits specified by the subscription
issues: Lifter Pro is 199 EGP/month, standard Coach Pro is 399 EGP/month, and
each eligible Founding coach receives two free Coach Pro months before a
continuous 299 EGP/month offer. Coach Free supports five active Players and
Coach Pro supports 30. Free and Pro AI allowances are five and 30 requests
respectively. A qualifying referred Coach's first successful payment grants one
month of credit to the referring Founding coach, up to two months. Billing and
offer-exposure events preserve the price, period, and promotion effective at
the event time rather than reconstructing them from a later price table.
`price_egp` is the final customer total for checkout and the actual paid amount
for a payment. `billing_period` is `month` or `none`; `promotion` is a stable
offer id or `none`.

### Glossary

- **Founding coach**: a Coach who qualifies from the closed trial for the
  launch grant of two free Coach Pro months and may convert to the 299 EGP
  monthly offer.
- **Referring Founding coach**: the Founding coach whose referral credit is
  earned when an eligible referred Coach makes a first successful payment.
- **Program draft**: an editable per-player copy created by assigning a
  template; it is not a committed Training program until published through the
  regular Coach publishing flow.

The actor column names the Account represented by PostHog distinct_id. That id
is always the immutable Account UUID. The common role, platform, app_version,
and env dimensions are present on every implemented event.

<!-- event-catalogue:start -->
| Status | Event | Owner | Trigger | Authoritative source | Origin | Actor / distinct_id | Required properties | Optional properties | Privacy notes and consuming metrics |
|---|---|---|---|---|---|---|---|---|---|
| implemented | account_created | #91 | Password or Google registration commits and the Account's Training ledger is ready. | Registry accounts and first_touch_acquisition inserts, followed by Training ledger initialization. | server | New Account created by registration. | role, platform, app_version, env, signup_phase, invite_used | none | No credentials or acquisition values are event properties. Signup, activation funnel, signup phase and invite cohorts. |
| implemented | onboarding_started | #91 | The first onboarding write commits, including disclosure, an intake answer, or a legacy start/answer. Reads do not count. | Training ledger onboarding_analytics start marker, written after the onboarding write. | server | Player who starts onboarding. | role, platform, app_version, env | none | No intake answers are sent. Onboarding start-to-completion funnel and time to complete. |
| implemented | onboarding_completed | #91 | The first successful onboarding completion commits and its completion time is persisted. | Training ledger onboarding_analytics completion marker and completed intake/program state. | server | Player completing onboarding. | role, platform, app_version, env, duration_seconds, prefilled_fields_count | none | Only bounded duration and answer count; answer values stay in the ledger. Completion rate and time-to-completion. |
| implemented | onboarding_step_viewed | #92 | The client displays one onboarding step. | Flutter screen display; no server write is implied. | client | Player viewing the step. | role, platform, app_version, env, step | none | step is an allowlisted screen identifier; no answer values. Step funnel and drop-off by platform/version. |
| implemented | coach_capability_granted | #96 | A Coach invite redemption commits and grants Coach capability. | Registry Account capability update. | server | Account receiving Coach capability. | role, platform, app_version, env | none | No invite code or inviter identity. Coach activation funnel. |
| implemented | coach_capability_disabled | #96 | A Coach explicitly disables Coach capability after active Assignments are ended. | Registry capability and relationship transitions. | server | Coach whose capability is disabled. | role, platform, app_version, env | none | No Player identity or relationship notes. Coach capability churn. |
| implemented | assignment_invite_issued | #96 | A Coach's single-use Assignment invite is stored. | Registry assignment_invites insert and committed roster count. | server | Coach issuing the invite. | role, platform, app_version, env, active_roster_size | none | Invite secret/hash is excluded. Invite issuance and roster-size distribution. |
| implemented | assignment_started | #96 | The Player consents and invite redemption plus active Assignment commit. | Registry assignments insert and invite claim in one transaction. | server | Coach roster owner; immutable Coach UUID is also the coach_id property. | role, platform, app_version, env, coach_id, active_roster_size, time_since_invite_seconds | none | No Player id, invite token, or consent text. Invite conversion, time-to-accept, roster growth and player activation. |
| implemented | assignment_ended | #96 | An active Assignment ends through a participant, Coach disablement, or account deletion. | Registry assignments status transition or deletion-time Assignment snapshot. | server | Coach roster owner; if that Coach is deleted, the surviving Player is the actor. | role, platform, app_version, env, ended_by, duration_seconds, active_roster_size | none | No counterpart id or free text. Assignment duration, roster churn and reason category. |
| implemented | invite_redemption_failed | #96 | A Player's Assignment invite redemption is refused. | Authoritative service refusal result and its coded reason; no domain state write occurs. | server | Player whose request was refused. | role, platform, app_version, env, reason_code | none | Only a fixed reason enum; no submitted code or response text. Invite reliability by refusal reason. |
| implemented | program_generated | #98 | A Training program version is persisted during onboarding, profile rebuild, player request, coach request, or lazy synthesis. | Training ledger training_programs and related program day/exercise rows. | server | Account that initiated generation, Player or Coach. | role, platform, app_version, env, trigger, day_count | none | Program, split, and exercise names are excluded. Generation funnel by trigger and plan behavior. |
| implemented | coach_program_published | #98 | A Coach publishes a Training program to an active Assignment after the new version commits. | Training ledger published program version, followed by registry assignment notice creation. | server | Coach publishing the program. | role, platform, app_version, env, day_count, first_for_assignment, is_coaching_action | none | No Player, Assignment, or exercise identifiers. Coaching activity, first publication, and coach activation. |
| implemented | program_exercise_swapped | #98 | A Player swaps or undoes a swap, or a Coach applies a substitution after the new version commits. | Training ledger program version containing the committed swap. | server | Account that performed the swap; role identifies Player or Coach. | role, platform, app_version, env | none | No exercise identity or reason text. Program interaction by actor role. |
| implemented | program_request_created | #98 | A Player's request commits to the registry. | Registry program_requests insert. | server | Player creating the request. | role, platform, app_version, env, kind | none | Only the request category; request reason and preference text are excluded. Request creation funnel by kind. |
| implemented | program_request_resolved | #98 | A Coach applies or declines a request, or a Player cancels it, after the registry transition commits. | Registry program_requests status and resolution timestamp. | server | Account making the transition; Coach for apply/decline, Player for cancellation. | role, platform, app_version, env, outcome, time_open_seconds, is_coaching_action | none | No request text or response. Resolution rate/time and Coaching action counts. |
| implemented | workout_completed | #97 | A Workout commit succeeds. Replayed idempotent sync emits no second event. | Training ledger session_commits and committed workout_sessions, workout_sets, and divergence rows. | server | Player whose Workout committed. | role, platform, app_version, env, set_count, exercise_count, load_complete_set_count, reps_complete_set_count, rir_complete_set_count, divergence_count, unplanned_exercise_count, captured_offline, sync_delay_seconds, is_first_workout, program_provenance, coached | none | Aggregate counts only; no dates, loads, reps, RIR values, exercise names, or Workout ids. Activation, retention, logging completeness, offline share and sync delay. |
| implemented | performed_date_corrected | #97 | A committed Workout's performed date changes and the correction is stored. A no-op emits nothing. | Training ledger performed_date_corrections insert. | server | Player whose Workout date was corrected. | role, platform, app_version, env | none | No dates or Workout id. Correction frequency and data-quality trend. |
| implemented | training_schedule_set | #97 | A new Training schedule version commits. | Training ledger training_schedules insert/version. | server | Player changing their schedule. | role, platform, app_version, env, days_per_week | none | Weekday identities and schedule text are excluded. Schedule adoption and adherence denominators. |
| implemented | schedule_pause_scheduled | #97 | A prospective Training schedule pause commits. | Training ledger training_pauses insert. | server | Player scheduling the pause. | role, platform, app_version, env, length_days | none | Pause dates and reason text are excluded. Pause use and schedule adherence analysis. |
| implemented | coach_alert_created | #99 | A new Coach alert row commits. A retry of the same alert does not emit again. | Registry Coach alert insert. | server | Coach who owns the alert. | role, platform, app_version, env, alert_kind | none | Category only; alert explanation and Player identity stay in the registry. Alert creation by kind and lifecycle funnel. |
| implemented | coach_alerts_viewed | #99 | An authorized alert-list read contains at least one new alert; emitted once per Coach per UTC day. | Successful authorized read and registry coach_analytics_daily_markers claim. | server | Coach viewing the alerts. | role, platform, app_version, env | none | No alert or Player identifiers. Alert-list adoption; not a Coaching action. |
| implemented | coach_alert_acknowledged | #99 | A Coach commits the new-to-acknowledged transition. Replays and system changes do not emit. | Registry Coach alert acknowledgement transition. | server | Coach acknowledging the alert. | role, platform, app_version, env, alert_kind, time_open_seconds, is_coaching_action | none | Category and bounded time only; no alert explanation or Player id. Time to acknowledgement and lifecycle by alert kind. |
| implemented | coach_alert_resolved | #99 | A Coach commits an open-to-resolved transition. System resolution does not emit. | Registry Coach alert resolution transition. | server | Coach resolving the alert. | role, platform, app_version, env, alert_kind, time_open_seconds, is_coaching_action | none | Category and bounded time only; no resolution text or Player id. Resolution rate/time and lifecycle by alert kind. |
| implemented | check_in_recorded | #99 | A Coach's check-in row commits; capture occurs before follow-up reconciliation. | Registry check_ins insert. | server | Coach recording the check-in. | role, platform, app_version, env, is_coaching_action | none | Check-in content, notes and Player id are excluded. Active coach, coaching action and check-in adoption. |
| implemented | player_history_viewed | #99 | An authorized Coach history or review read passes the Assignment gate; emitted once per Coach, Assignment and UTC day. | Successful authorized read and registry coach_analytics_daily_markers claim. | server | Coach reading assigned Player history. | role, platform, app_version, env | none | No Player or Assignment identifiers and no training facts. History-review adoption; not a Coaching action. |
| implemented | workout_sync_failed | #97 | The authenticated client reports a failed Workout draft sync attempt. | Client report to `POST /workouts/sync-failures`; capture uses a random UUID per report and writes no analytics failure row. | server | Player whose sync attempt failed. | role, platform, app_version, env, sync_failure_reason, attempt | none | Coded category and bounded attempt only; no response text or Workout id. Sync failure trends by reason, platform and version. |
| implemented | ai_request_completed | #100 | One inference turn ends after its caller-owned write; an event is emitted even for a failed turn with no model calls. | Persisted model_usage rows grouped by turn_id; caller turn state supplies zero-row outcomes. | server | Account that made the inference request. | role, platform, app_version, env, plan, use_case, models, model_count, input_tokens, output_tokens, tokens, cost_usd, estimated, latency_ms, outcome, finish_reason, turns_today, requests_per_minute_limit, tokens_today, tokens_daily_limit | none | Token counts, model ids and cost aggregates only; no prompts, completions, messages, or credentials. AI economics, latency, outcomes, and use by role/plan. |
| implemented | ai_request_limited | #100 | Admission refuses a user turn after the coded limit-hit record commits. | Registry model_limit_hits row and current capability plan. | server | Account whose request was limited. | role, platform, app_version, env, plan, limit | none | Limit and plan enums only; no request content. Limit rates by role, plan and limit. |
| implemented | workout_started | #92 | A new Active Workout is saved locally before logger navigation; resuming an existing one is not another start. | Flutter local Workout draft creation. | client | Player starting the Workout. | role, platform, app_version, env | none | No local Workout id or content. Started-to-completed funnel and abandonment. |
| implemented | workout_draft_discarded | #92 | A Player explicitly discards an Active Workout or unsynced draft; the client deduplicates locally. | Flutter local draft discard action. | client | Player discarding the draft. | role, platform, app_version, env | none | No local Workout id or contents. Workout abandonment trend. |
| planned | coach_roster_cap_blocked | #57 Enforce plan-aware coach roster caps | A Coach is refused a roster increase because the effective plan cap is reached. | Committed registry entitlement and active Assignment count at the refusal. | server | Coach whose roster change was refused. | capability, plan, active_roster_size, roster_cap, price_egp, billing_period, promotion | none | No Player ids or invite secrets. During the two free Founding coach months the blocked Coach Pro offer is 0 EGP/month with founding_free_two_months; eligible later conversion is 299 EGP/month with founding_299_monthly; regular Coach Pro is 399 EGP/month; Coach Free is 0 with no period. Roster-cap blocks and upgrade opportunity. |
| planned | checkout_started | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout; #63 Convert founders to the 299 EGP plan | A verified Account starts checkout for Lifter Pro, Coach Pro, or the Founding coach offer. | Committed web checkout attempt with the displayed offer copied into the attempt record. | server | Account starting checkout. | capability, plan, price_egp, billing_period, promotion | none | Do not send checkout/session ids, payment credentials or email. Preserve the shown offer at start: Lifter Pro 199 EGP/month, regular Coach Pro 399 EGP/month, or Founding coach Coach Pro 0 EGP/month during founding_free_two_months and 299 EGP/month during founding_299_monthly. Checkout-start funnel by offer. |
| planned | checkout_succeeded | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout; #63 Convert founders to the 299 EGP plan | A verified provider success commits the first subscription entitlement. | Authenticated payment event and committed subscription/entitlement write. | server | Account whose capability was granted. | capability, plan, price_egp, billing_period, promotion | none | Provider signatures, transaction ids and payment details stay out of analytics. Preserve the actual charged amount and offer: Lifter Pro 199 EGP/month, regular Coach Pro 399 EGP/month, or eligible Founding coach 299 EGP/month. Verified purchase conversion. |
| planned | checkout_failed | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout; #63 Convert founders to the 299 EGP plan | A verified provider failure leaves the prior entitlement unchanged. | Authenticated provider outcome and committed payment-attempt status. | server | Account whose checkout failed. | capability, plan, price_egp, billing_period, promotion, outcome | none | Coded outcome only; no gateway message or credentials. Preserve the attempted Lifter Pro 199 EGP/month, regular Coach Pro 399 EGP/month, or Founding coach 299 EGP/month offer and promotion. Checkout failure and recovery funnel. |
| planned | payment_succeeded | #61 Handle subscription renewal and expiry | A renewal or later subscription payment succeeds. | Verified provider webhook and committed payment ledger row. | server | Account paying for the capability. | capability, plan, price_egp, billing_period, promotion | none | No payment instrument or provider identifiers. Preserve the exact amount, monthly period, and promotion applied to that payment. Renewal success and retention. |
| planned | payment_failed | #61 Handle subscription renewal and expiry | A renewal or later subscription payment fails. | Verified provider webhook and committed payment-attempt status. | server | Account with the failed payment. | capability, plan, price_egp, billing_period, promotion, outcome | none | Coded outcome only. Preserve the attempted contract price, monthly period and promotion at failure time. Payment recovery funnel. |
| planned | payment_refunded | #61 Handle subscription renewal and expiry | A previously successful payment is refunded or reversed. | Verified provider reversal and committed refund/payment ledger row. | server | Account whose payment was reversed. | capability, plan, price_egp, billing_period, promotion | none | No provider reference or free-text refund reason. Preserve the original charged amount, period and promotion from the paid row. Refund rate; #64 consumes this event when deciding whether to emit referral_reversed. |
| planned | subscription_plan_changed | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout; #61 Handle subscription renewal and expiry; #62 Grant founding coaches two free months; #63 Convert founders to the 299 EGP plan | A committed checkout, founding grant, renewal, expiry or other lifecycle transition changes a capability's effective plan. | Committed registry entitlement/subscription transition. | server | Account whose plan changed. | capability, prior_plan, plan, price_egp, billing_period, promotion | none | No counterpart identity. Preserve the effective price/period/promotion at transition: Lifter Pro 199 EGP/month; Coach Pro 399 EGP/month; the free Founding coach grant 0 EGP/month with founding_free_two_months; eligible Founding coach conversion 299 EGP/month with founding_299_monthly; Free is 0/no period. Plan conversion and churn. |
| planned | subscription_cancelled | #61 Handle subscription renewal and expiry | A subscriber cancels renewal; access remains through its paid-through end. | Committed subscription renewal/cancellation status. | server | Account cancelling the subscription. | capability, plan, price_egp, billing_period, promotion | none | No cancellation reason text. Preserve the active paid price, monthly period and promotion at cancellation. Cancellation and paid-through retention. |
| planned | subscription_expired | #61 Handle subscription renewal and expiry | Paid-through access ends and the capability downgrades. | Committed subscription expiry and entitlement transition. | server | Account whose subscription expired. | capability, prior_plan, plan, price_egp, billing_period, promotion | none | No payment/provider identifiers. Preserve the ending paid contract price and promotion; the new Free plan is 0 with no billing period. Expiry and downgrade. |
| planned | subscription_status_viewed | #60 Use web subscriptions in the Android app; #61 Handle subscription renewal and expiry | A signed-in Android or web Account opens its subscription-status surface. | Client screen exposure using the server-owned entitlement snapshot. | client | Account viewing their own status. | capability, plan, entitlement_status | none | No payment record, price, billing period, promotion, or counterpart identity is sent; Android status exposure is plan/status only. Entitlement-status adoption. |
| planned | founding_status_granted | #62 Grant founding coaches two free months | A durable closed-trial Coach record qualifies at public launch and the grant commits. | Trial-coach eligibility record and one-time Coach entitlement grant. | server | Eligible Founding coach. | capability, plan, free_months, price_egp, billing_period, promotion | none | No username or manual status flag. Preserve Coach Pro at 0 EGP/month for two months with founding_free_two_months. Founding coach eligibility and grant coverage. |
| planned | promotion_period_started | #62 Grant founding coaches two free months; #63 Convert founders to the 299 EGP plan | A committed Founding coach grant or paid offer begins. | Committed promotion grant or Founding coach opt-in transition. | server | Account receiving the promotion. | capability, plan, price_egp, billing_period, promotion | none | No payment mandate or payment details. Preserve either the two free Coach Pro months at 0 EGP/month with founding_free_two_months or the paid offer at 299 EGP/month with founding_299_monthly. Promotion starts and eligibility. |
| planned | promotion_period_ended | #62 Grant founding coaches two free months; #63 Convert founders to the 299 EGP plan | A committed promotional entitlement period reaches its end or is lost under its rules. | Committed promotion/entitlement transition and effective-through timestamp. | server | Account whose promotion ended. | capability, plan, price_egp, billing_period, promotion | none | No payment instrument. Preserve the ending promotion and its price/period: founding_free_two_months at 0 EGP/month or founding_299_monthly at 299 EGP/month. Promotion completion and paid-rate changes. |
| planned | founding_plan_converted | #63 Convert founders to the 299 EGP plan | A Founding coach explicitly opts into recurring billing before the earned free period ends and the subscription commits. | Affirmative billing consent plus verified checkout and Coach subscription write. | server | Founding coach converting. | capability, plan, price_egp, billing_period, promotion | none | No inferred consent or automatic charge. Preserve the 299 EGP monthly rate and founding_299_monthly promotion. Founding coach conversion and deadline funnel. |
| planned | referral_qualified | #64 Award and reverse founding referral months | A referred Coach makes their first successful payment while the referring Founding coach is eligible; one reward month commits. | First successful payment, immutable first-touch referral link, and committed reward-credit row. | server | Referring Founding coach whose credit is earned. | capability, referred_plan, price_egp, billing_period, promotion, reward_months, earned_months_total | none | Do not include referred Account id, email, or invite. Preserve the referred Coach's actual first payment amount and promotion plus the reward promotion; each payment grants one month, capped at two. Referral qualification and reward cap. |
| planned | referral_reversed | #64 Award and reverse founding referral months | A qualifying first payment is refunded and an unused reward credit is removed; used months are not billed back. | Consumed payment_refunded outcome plus committed reward-credit reversal. | server | Referring Founding coach whose unused credit was removed. | capability, referred_plan, price_egp, billing_period, promotion, reward_months, earned_months_total | none | No referred identity or refund text. Preserve the original payment's price/period/promotion and the reversed reward month. Referral reversal and unused-credit balance. |
| planned | coach_free_grace_started | #65 Apply the over-cap Coach Free grace | Coach Pro ends while the Coach has more than five active Players and the 14-day grace begins at paid-through end. | Committed entitlement end, active Assignment count and grace deadline. | server | Coach entering the over-cap grace. | capability, prior_plan, plan, active_roster_size, roster_cap, grace_days, price_egp, billing_period, promotion | none | No Player ids or training data. Preserve the ending Pro price/promotion: 399 EGP/month regular or 299 EGP/month with founding_299_monthly; Coach Free is 0/no period. Grace entry and roster reduction. |
| planned | coach_free_grace_expired | #65 Apply the over-cap Coach Free grace | Fourteen days after paid-through end, an over-cap Coach loses write access until Pro returns or the roster reaches five. | Committed grace deadline, entitlement and active Assignment count. | server | Coach whose grace expired. | capability, prior_plan, plan, active_roster_size, roster_cap, grace_days, price_egp, billing_period, promotion | none | No Player ids or blocked request content. Preserve the ending paid price and promotion; Coach Free is 0/no period. Grace expiry and restoration. |
| planned | pricing_viewed | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout; #63 Convert founders to the 299 EGP plan | A web Account sees one Lifter Pro, Coach Pro, or Founding coach offer. | Client pricing-page card exposure. | client | Account viewing the offer. | capability, plan, price_egp, billing_period, promotion | none | No click identifiers or free text. Preserve the displayed regular offers (Lifter Pro 199 EGP/month; Coach Pro 399 EGP/month) or Founding coach offer (0 EGP/month during founding_free_two_months; 299 EGP/month during founding_299_monthly). Pricing exposure-to-checkout funnel. |
| planned | upgrade_prompt_viewed | #58 Sell Lifter Pro through web checkout; #59 Sell Coach Pro through web checkout | A web Account sees an upgrade prompt for regular Lifter Pro or Coach Pro. | Client prompt exposure. | client | Account seeing the prompt. | capability, plan, price_egp, billing_period, promotion | none | No Player/Coach counterpart identity or free text. Preserve the displayed 199 or 399 EGP monthly offer and promotion. Upgrade exposure and checkout conversion. |
| planned | template_created | #305 Template library: create, name, edit, duplicate and archive; #307 Save a player's program as a template | A Coach creates a Coach-only template or saves a reviewed Player Program structure after the template record commits. | Coach-owned template catalog insert; #307 reads an active Player Program or open Program draft through the Coach gate and copies only reviewed structure. | server | Coach who owns and creates the template. | template_kind, source | none | Coach-only. No Player id, template id, name, description, notes, prescriptions, exercise names or other free text. Template creation and save-from-Program usage. |
| planned | template_viewed | #305 Template library: create, name, edit, duplicate and archive | A Coach opens the Coach-only template library. | Successful client library display backed by the Coach-owned template catalog. | client | Coach viewing the library. | template_kind | none | Coach-only. No template id, name, description, Player identity or free text. Template discovery. |
| planned | template_applied | #306 Assign a template to one or more players as independent drafts | A Coach assigns a template and per-Player Program draft copies commit for active Assignments. | Future template catalog source and independent per-Player Program draft writes; optional publishing follows the regular Coach publishing flow. | server | Coach assigning the template. | template_kind, player_count, assignment_outcome | none | Coach-only. Assignment creates editable Program drafts, not a committed Training program; no Player ids, template id, name or exercise data. Draft creation/partial outcome and later publication funnel. |
<!-- event-catalogue:end -->

### Planned properties

These names are reserved by planned event contracts only. They are not
accepted by the implemented code catalogue; when an owning ticket implements
an event, it must add validated property types and extend the sync test.
Properties already defined below or in the code catalogue remain governed by
those definitions.

| Property | Planned type and allowed values | Meaning |
|---|---|---|
| `capability` | `player` or `coach` | Capability whose subscription, price, roster rule or promotion changed. |
| `prior_plan` | `free`, `pro`, or `unknown` | Capability plan immediately before the transition. |
| `price_egp` | Integer: 0, 199, 299, or 399 | Historical offer/charge amount effective when the event fires. |
| `billing_period` | `month` or `none` | Historical charge period; `none` is used for Free. |
| `promotion` | `none`, `founding_free_two_months`, or `founding_299_monthly` | Stable promotion that applied at the event time. |
| `roster_cap` | Integer: 5 or 30 | Effective Coach Free or Coach Pro active-Player cap. |
| `entitlement_status` | `active`, `cancelling`, or `expired` | Status shown by the subscription view; no price or billing fields accompany it. |
| `free_months` | Integer: 2 | Number of Coach Pro months granted to an eligible Founding coach. |
| `referred_plan` | `coach_pro` | Plan on the referred Coach's qualifying first payment. |
| `reward_months` | Integer: 1 | Months earned or reversed by one referral event. |
| `earned_months_total` | Integer from 0 to 2 | Founding coach's cumulative referral credit after the event. |
| `grace_days` | Integer: 14 | Duration of the over-cap Coach Free grace period. |
| `template_kind` | `program` | Coach-only reusable Program template type. |
| `source` | `coach_created` or `saved_from_player_program` | How a Coach-owned template was created. |
| `player_count` | Integer from 0 to 30 | Number of active Assignment Players with a draft outcome. |
| `assignment_outcome` | `all_drafts_created`, `partial`, or `none` | Aggregate result of assigning one template; no per-Player identity is sent. |

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
| `app_version` | Safe version label or `unknown`; IP literals rejected | Flutter build name; server events use `X-MAYOS-Client`. |
| `env` | `development`, `production`, or `test` | Release Flutter events use `production`; server uses `MAYOS_ENV`, defaulting to `development`. |
| `signup_phase` | `closed_trial` or `public` | Release phase at account creation; also set once on the person. |
| `utm_source` | Lowercase `[a-z0-9._-]`, 1–64 characters; IP literals rejected | First-touch source label; set once on the person and stored in `first_touch_acquisition`. |
| `utm_medium` | Lowercase `[a-z0-9._-]`, 1–64 characters; IP literals rejected | First-touch medium label; set once on the person and stored in `first_touch_acquisition`. |
| `utm_campaign` | Lowercase `[a-z0-9._-]`, 1–64 characters; IP literals rejected | First-touch campaign label; set once on the person and stored in `first_touch_acquisition`. |
| `referrer_host` | Lowercase hostname, up to 253 characters; IP literals rejected | Host extracted from the first web document referrer; paths and query strings are discarded. |
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
| `is_coaching_action` | Boolean | True for a recorded coaching action. Coach publication, request resolution, alert acknowledgement or resolution, and check-in recording are true; Player cancellation is false. |
| `kind` | `exercise_substitution` or `split_change` | Program request category. Request reasons and split preference are never sent. |
| `alert_kind` | `missed_expected_days`, `follow_up_due`, `profile_change`, `stall`, `deload_recommended`, or `performance_regression` | Coach alert category. Alert explanations are never sent. |
| `outcome` | `applied`, `declined`, `cancelled`, `ok`, `error`, or `interrupted` | Program request's committed resolution or the result of an inference turn. A decline response is never sent. |
| `time_open_seconds` | Bounded nonnegative integer | Whole seconds between request or alert creation and resolution, or alert creation and acknowledgement, capped at one year. |
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
| `use_case` | `chat`, `onboarding`, `onboarding_complete`, `program_active`, `program_generate`, `profile_rebuild`, `coach_generate_draft`, `coach_program_request`, `coach_assistant`, `checkpoint_review`, or `other` | Allowlisted ADR 038 metering purpose category. Unknown purpose labels map to `other`. |
| `plan` | `free`, `pro`, or `unknown` | Current plan for the capability matching the event role: Lifter plan for Player inference, Coach plan for Coach inference. |
| `models` | List of 1–5 configured model ids or `other` | Distinct model ids found in the committed metering rows, bounded to five; any id not in the model factory's current configuration maps to `other`. A zero-row turn uses `other`. |
| `model_count` | Integer from 1 to 5 | Number of distinct model ids included in `models`. |
| `input_tokens` | Integer from 0 to 10,000,000 | Sum of input tokens from the user turn's committed `model_usage` rows. |
| `output_tokens` | Integer from 0 to 10,000,000 | Sum of output tokens from the user turn's committed `model_usage` rows. |
| `tokens` | Integer from 0 to 20,000,000 | Input plus output tokens from the user turn's committed `model_usage` rows. |
| `cost_usd` | Number from 0 to 100,000 | Sum of the recorded `cost_usd` values from those same metering rows. |
| `estimated` | Boolean | True if any of the turn's metering rows used estimated token counts. |
| `latency_ms` | Integer from 0 to 31,557,600 | Time spent in the inference scope, excluding any caller-owned write that follows it. |
| `finish_reason` | `stop`, `length`, `tool_calls`, `content_filter`, `other`, or `unknown` | Provider finish reason mapped to a small vocabulary; `unknown` means none was available. |
| `turns_today` | Integer from 0 to 1,000,000 | Distinct non-null `turn_id` values on this account's metering rows since UTC midnight, excluding `checkpoint_review` under ADR 052 just like `tokens_today`. A turn with no model call emits its event but does not count here. |
| `requests_per_minute_limit` | Integer from 0 to 1,000,000 | Current `MODEL_RATE_LIMIT_REQUESTS` setting; zero disables the per-minute request limit. MAYOS has no daily turn ceiling. |
| `tokens_today` | Integer from 0 to 100,000,000 | Account token usage since UTC midnight, using the same exclusion rule as the daily token admission check; `checkpoint_review` is excluded under ADR 052. |
| `tokens_daily_limit` | Integer from 0 to 100,000,000 | Current `MODEL_DAILY_TOKEN_LIMIT` setting; zero disables this limit. |
| `limit` | `requests_per_minute` or `daily_tokens` | The coded model limit that refused admission. |

## PostHog and operational database boundary

PostHog is for product behavior: funnels, trends, retention, cohorts and feature
adoption. It is useful for questions about which flows people use and where they
stop. It is not the financial ledger and cannot replace account, entitlement,
assignment, Training ledger or model_usage records. Use operational database
queries for current state, and a BI layer for joined historical finance and
cohort reporting. Event delivery is fire-and-forget, so authoritative writes can
outlive a lost analytics event if the process exits between commit and capture.

The server uses the PostHog SDK background queue, sends nothing without a
project key, and is a no-op in tests. Person deletion uses the MAYOS analytics
interface and the PostHog persons API. Keep production, development and test
projects separated. Before a key is enabled, configure project-level client IP
discard as described above.

## Metrics that wait on payments, production data or BI

- **Payments and subscription writes:** verified paid conversion, payment
  success/failure, refund rate, cancellation, expiry, founder conversion, and
  event-level checkout funnels remain planned until the subscription tickets
  create authoritative payment and entitlement records. PostHog will not be the
  source for MRR or revenue totals.
- **Production data:** acquisition-channel mix, public-launch conversion,
  retention baselines, operating reliability, and founding-cohort outcomes need
  real production traffic. Closed-trial subscriptions do not exist and no trial
  participant is charged.
- **Operational database or BI:** MRR, recognized revenue and revenue by source,
  payment reconciliation, contribution margin, infrastructure cost per user,
  detailed roster/history joins, and the 10,000-active-accounts report (#75).
  Revenue-by-source joins payment records to immutable first-touch acquisition;
  contribution margin also needs provider fees and operating costs. The
  10,000-active-accounts report uses the repository's Active account definition
  and authoritative records.
- **Infrastructure cost:** model_usage supports measured AI cost; it does not
  include hosting, storage, email or other infrastructure spend. Therefore
  total infrastructure cost per user remains a BI/operations metric.

## Dashboards

Build these five dashboards manually in PostHog. Apply date range and environment
filters to all event insights. Implemented events carry role, platform,
app_version, and env. `signup_phase` is a person property and is an event
property only where listed; use the person cohort for other event breakdowns.
`coached` is available on Workout events and person state. `plan` is available
on AI and future subscription events; do not assume a paid-plan breakdown exists
for older events. Detailed financial amounts always reconcile to operational
records.

### Founder / business

| Insight (type) | Events or database source | Filters / breakdowns |
|---|---|---|
| Coach activation: capability granted → program published → invite issued → Assignment started → Player's first Workout completed (joined funnel) | coach_capability_granted, coach_program_published, assignment_invite_issued, assignment_started, workout_completed with is_first_workout | signup_phase, platform, role, coached; the last event is attributed to the Player, so connecting it to the Coach's Assignment requires a registry/BI join across distinct_id values. |
| Player activation: Account created → onboarding started → completed → program generated/published → first Workout (funnel) | account_created, onboarding_started, onboarding_completed, program_generated, coach_program_published, workout_completed with is_first_workout. `coach_program_published` is attributed to the Coach, so a coached Player's publication step needs a registry/BI join on the Assignment; in PostHog use `program_generated` for independent Players. | coached, signup_phase, platform, role, trigger. |
| Invite-to-Assignment and Assignment-to-first-Workout elapsed time (trend) | assignment_invite_issued, assignment_started, workout_completed; assignment facts for authoritative joins | platform, signup_phase, coached; event time_since_invite_seconds and is_first_workout. |
| Active Accounts, WAU/MAU and W1/W2/W4/W8/M3/M6/M12 cohort retention (retention) | account_created cohorts; workout_completed for Players; recorded Coaching action events for Coaches | role, signup_phase, platform, coached, AI adoption, alert adoption. Count a Coach as active only for a Coaching action. |
| Acquisition activation and founding conversion (funnel / cohort) | account_created and first_touch_acquisition in the registry; planned pricing, checkout, founding and referral events | normalized UTM source/medium/campaign, referrer host, referring Coach, signup_phase, platform, plan. Money reconciles in BI. |

### Coach product

| Insight (type) | Events or database source | Filters / breakdowns |
|---|---|---|
| Coach activation: capability granted → program published → invite issued → Assignment started → Player's first Workout completed (joined funnel) | coach_capability_granted, coach_program_published, assignment_invite_issued, assignment_started, workout_completed with is_first_workout | signup_phase, platform, coached, plan when present; the Workout is attributed to a different Player distinct_id, so joining it to the Coach's Assignment requires a registry/BI join. |
| First committed Coaching action after Coach activation (funnel) | coach_capability_granted, coach_program_published, assignment_invite_issued, assignment_started, check_in_recorded, program_request_resolved, coach_alert_acknowledged, coach_alert_resolved | signup_phase, platform, plan when present; exclude reads and invite issuance from active-coach counts. |
| Active Coaches by week/month and Coaching actions per active Coach (trend) | check_in_recorded, coach_program_published, applied/declined program_request_resolved, coach_alert_acknowledged, coach_alert_resolved | role, signup_phase, platform, plan, roster size. Only recorded Coaching actions qualify. |
| Coach alert created → viewed → acknowledged/resolved, with time to action (funnel / trend) | coach_alert_created, coach_alerts_viewed, coach_alert_acknowledged, coach_alert_resolved | alert_kind, platform, signup_phase, plan. Viewed is daily deduplicated and cannot be joined to one alert id. |
| Assignment growth, duration, end reason and roster size (trend / distribution) | assignment_invite_issued, assignment_started, assignment_ended, registry assignments | coach role, platform, signup_phase, plan; use registry for exact current roster. |
| Program request flow and history-review adoption (funnel / trend) | program_request_created, program_request_resolved, player_history_viewed | kind, outcome, role, platform, plan; history reads are not Coaching actions. |
| Coach template library, save, assignment and draft creation (funnel) | planned template_viewed, template_created, template_applied; independent per-Player Program drafts and later published Training programs | Coach role, platform, coached, plan; template access and assignment are Coach-only, and assignment creates Program drafts before optional publication. |

### Player product

| Insight (type) | Events or database source | Filters / breakdowns |
|---|---|---|
| Player activation through onboarding, program and first completed Workout (funnel) | account_created, onboarding_started, onboarding_step_viewed, onboarding_completed, program_generated, coach_program_published, workout_completed. `coach_program_published` is attributed to the Coach, so a coached Player's publication step needs a registry/BI join on the Assignment; in PostHog use `program_generated` for independent Players. | coached versus independent, signup_phase, platform, role, trigger. |
| WAU/MAU and W1/W2/W4/W8/M3/M6/M12 retention (retention) | account_created cohorts and workout_completed activity | coached, signup_phase, platform, role, AI adoption, alert adoption. Workout activity is the Player return signal. |
| Workout starts, completions and discarded drafts (funnel / trend) | workout_started, workout_draft_discarded, workout_completed | platform, app_version, coached, signup_phase; start/discard events are client-only. |
| Logging completeness, offline capture and sync delay (trend) | workout_completed aggregate counts and schedule events; Training ledger for adherence calculations | platform, app_version, coached, plan once subscription events exist. Never expose individual training values. |

### AI economics

| Insight (type) | Events or database source | Filters / breakdowns |
|---|---|---|
| AI cost and tokens by Account, role, plan, use case and model (trend / distribution) | ai_request_completed; reconcile with model_usage joined by turn_id | role, plan, use_case, models, estimated, outcome, platform. Use model_usage as cost authority. |
| Requests per Account per UTC day and p50/p90/p95/p99 percentiles (distribution) | ai_request_completed grouped by distinct_id and event date; model_usage for metered-call reconciliation | role, plan, use_case, signup_phase. A user turn is one request even when it makes multiple model calls. |
| Limit-hit rate and current usage against limits (trend) | ai_request_limited and ai_request_completed; model_limit_hits and model_usage | role, plan, limit, use_case, environment. |
| Latency, outcomes, finish reasons and estimated-cost share (trend) | ai_request_completed; service logs for server-wide latency/error detail | role, plan, model, use_case, outcome, finish_reason, estimated. |

### Reliability

| Insight (type) | Events or database source | Filters / breakdowns |
|---|---|---|
| Reported Workout sync failures and reasons (trend) | workout_sync_failed | platform, app_version, sync_failure_reason, attempt, role. |
| Offline Workout completion share and capture-to-commit delay (trend) | workout_completed | platform, app_version, captured_offline, sync_delay_seconds, coached. |
| Failed-sync reports versus successful commits over time (trend) | workout_sync_failed and workout_completed; sync API request logs for a denominator | platform, app_version, date. Events do not share a Workout id, so this is a time-bucket comparison, not a per-draft conversion. |
| AI limit pressure and inference failures (trend) | ai_request_limited, ai_request_completed; service logs for transport/provider incidents | role, plan, use_case, model, outcome, limit, app_version. |
| Assignment invite redemption failures by coded reason (trend) | invite_redemption_failed | reason_code, platform, app_version, role. |
| Alert lifecycle delay and unresolved volume (trend) | coach_alert_created, coach_alert_acknowledged, coach_alert_resolved; operational alert rows for current open count | alert_kind, platform, signup_phase, plan. |

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
