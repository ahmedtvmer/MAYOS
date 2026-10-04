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
- Mutable person properties are `is_player` and `is_coach`. The initial
  `signup_phase` is set once from `MAYOS_RELEASE_PHASE` (`closed_trial` by
  default; `public` after launch).
- Every server event carries `role`, `platform`, `app_version`, and `env`.
  `X-MAYOS-Client` uses `platform/version` (for example, `android/1.2.3`);
  missing or invalid headers resolve to `unknown`. The service owns that
  resolution in one helper so the client-header implementation can extend it.
- `env` uses one of `development`, `production`, or `test` from `MAYOS_ENV`;
  the default is `development`. Fly sets `MAYOS_ENV=production` explicitly.
  `TESTING=1` or no `POSTHOG_API_KEY` disables sends.
  `POSTHOG_HOST` can override the default EU endpoint
  (`https://eu.i.posthog.com`).
- The adapter disables exception autocapture and logs no captured exceptions;
  GeoIP enrichment is disabled. Events never contain usernames, emails, passwords, tokens, IP
  addresses, free text, onboarding answers, prompts, completions, or workout
  contents.
- Event UUIDs are UUID5 values derived from the event name and its domain key.
  For these account-scoped events, the domain key is the immutable account id.
- The code catalogue and current server events are contract-tested for exact
  name parity. The strict recording sink rejects unknown events, extra or
  missing properties, and values outside each property's safe type or
  vocabulary. The production adapter drops and logs contract violations.

## Current server event catalogue

<!-- event-catalogue:start -->
| Event | Origin | Trigger | Properties |
|---|---|---|---|
| `account_created` | server | A password or Google registration has committed and its account ledger is ready. | `role`, `platform`, `app_version`, `env`, `signup_phase`, `invite_used` |
| `onboarding_started` | server | The first committed onboarding write: disclosure, first named answer, or legacy start/answer. Reads do not create this event. | `role`, `platform`, `app_version`, `env` |
| `onboarding_completed` | server | The first successful onboarding completion has committed and its completion time is persisted. Retries and replayed confirmation do not create another event. | `role`, `platform`, `app_version`, `env`, `duration_seconds`, `prefilled_fields_count` |
<!-- event-catalogue:end -->

### Property definitions

| Property | Type and allowed values | Meaning |
|---|---|---|
| `is_player` | Boolean person property | The Account has Player capability. |
| `is_coach` | Boolean person property | The Account has Coach capability. |
| `role` | `player`, `coach`, or `unknown` | Capability under which the action occurred. |
| `platform` | `android`, `web`, or `unknown` | Resolved from `X-MAYOS-Client`. |
| `app_version` | Safe version label or `unknown` | Resolved from `X-MAYOS-Client`. |
| `env` | `development`, `production`, or `test` | `MAYOS_ENV`, defaulting to `development`. |
| `signup_phase` | `closed_trial` or `public` | Release phase at account creation; also set once on the person. |
| `invite_used` | Boolean | Whether registration consumed a new-account Coach invite. No invite code is sent. |
| `duration_seconds` | Bounded nonnegative integer | Elapsed whole seconds from the first persisted onboarding start to completion. |
| `prefilled_fields_count` | Integer from 0 to 100 | Number of legacy-prefilled answers at completion. Answer values are never sent. |

## PostHog and operational database boundary

PostHog is for product behavior, funnels, retention, cohorts, and adoption. The
registry and Training ledger remain the source for account state, assignments,
rosters, completed workouts, and acquisition or financial records. Revenue,
MRR, payment reconciliation, contribution margin, and infrastructure cost are
not reconstructed from analytics events.

The service uses the PostHog SDK's background queue. It sends no events without a
key and never sends from test mode. Person deletion is exposed by the MAYOS
analytics interface for account-deletion work; account deletion and its retry
policy are owned by the account-deletion implementation.
