# MAYOS — Coaching Platform & Android Delivery Plan

> Status: Approved for the closed Android trial · Updated: 2026-09-23
> Scope: Migrate MAYOS to a cloud-backed **two-capability coaching platform**
> (coach + player) with a Flutter Android product client distributed via Google
> Play. The closed trial targets Android only. Fly.io serves the API only
> (uvicorn). The Streamlit UI is legacy, serves no users, and is scheduled for
> deletion after mobile cutover. The local GGUF backend remains available for
> development and evaluation; production uses a hosted model selected by the
> parity gate.
>
> The player-only v1 plan is superseded. Phase 0's hosted parity gate passed;
> the remaining trial path is C1–C3
> and workout sync → D → C5 → P. C4 coach AI can be enabled only after its
> separate privacy and eval gates. Directory discovery and payments follow a
> successful trial. Re-estimate delivery time from this scope before starting.
>
> Coaching terms are defined in [CONTEXT.md](CONTEXT.md). Earlier engine ADRs
> are in [DECISIONS.md](DECISIONS.md), including accepted coaching decisions.

## 1. Locked Decisions

| Decision           | Choice                                                             |
|--------------------|--------------------------------------------------------------------|
| Product model      | One account may train, coach, or both; capabilities are not exclusive |
| Client packaging   | Flutter Android is the product client; capability-gated navigation and feature-module layout |
| Player assistant   | Qwen3.5-9B via DeepInfra, non-reasoning; measured 62/65 standard and 15/15 generalization |
| Coach assistant    | Qwen3.5-27B via DeepInfra (player-scoped analysis + split help)     |
| Judge LLM          | Qwen3.5-27B via DeepInfra (eval-only; outside production requests)  |
| Assignment         | Short-lived single-use bearer code; instant binding after player consent, coach notified and may revoke; directory requests after trial |
| Coach privacy      | `discoverable` flag, **default off** — invisible unless opted in   |
| Coach cardinality  | One active coach per player (switching = unassign + rebind)        |
| Split authority    | Auto-program self-service until the coach publishes the first program; then player program changes, including substitutions, become coach requests |
| Workout logging    | Player may record skipped or unplanned exercises without changing the program; offline drafts sync idempotently |
| Offline conflict   | Sync a historical workout against its captured program version even if the coach has since published a new program |
| Player chat        | Private — never visible to coaches                                 |
| Alerts             | In-app alert center + badges (no push in the trial)                 |
| Scale target       | < 100 users, single replica (SQLite single-writer)                 |
| Distribution       | Free Android-only Google Play closed trial with owner-invited coaches and 5–10 coach-player pairs for four weeks |
| API server         | Fly.io, Frankfurt (fra), shared-cpu-1x 1–2 GB, 10 GB volume        |
| Object storage     | Cloudflare R2 — daily snapshots; deletion removes user-specific copies; restricted catalog recovery backups may retain deleted rows up to 30 days |
| Email              | Resend via existing SMTP transport; new invite/request notices need templates |
| Repo layout        | Monorepo — Flutter client in `mobile/`                             |
| Trial spend guard  | Alert owner at $50/month projected spend; per-account model rate limits; review before wider rollout |

## 2. Product Model

### Coach
Receives an owner invitation to enable the coach capability → creates a coach
profile (display name, bio, specialization, capacity) → generates single-use,
capacity-bound invite codes → invites players. A coach cannot assign their own
account as a player. Directory discovery is unavailable during the closed trial.

Coach console: roster of assigned players with alert badges; per-player workout
log and telemetry drill-down; alert center; program assignment; split-change
and substitution-request queues; a coach assistant scoped to a selected player's minimal
telemetry snapshot, enabled only after its privacy boundary and eval gate pass.

### Player
Registers or enables the player capability (optional invite; without one,
retains the current self-service experience) → onboarding → **temporary
auto-program** (the existing deterministic generator) → logs workouts and
chats privately with the hosted player assistant → coach (once bound) can
publish a coach-authored program.

### Authority
- Auto-split is fully player-self-service.
- An active coaching assignment alone does not remove self-service. When the
  coach publishes the first coach-authored program, subsequent player requests
  to change its structure become **coach request events**. Enforce this at
  every program write path, including chat `program_mutation`, direct program
  generation, profile-triggered regeneration, onboarding, and exercise
  substitution. The coach applies substitutions to a coach-controlled program;
  a player request alone never changes it.
- A player may record a skipped or unplanned performed exercise truthfully in
  their workout log. It is flagged for the assigned coach and does not alter
  the prescribed program.
- Coach publication makes the new program active immediately and notifies the
  player. The player may request a change or end the assignment; acceptance is
  not a separate activation step.
- One active coach per player; switching is unassign-then-rebind.
- After unassignment, the player may edit the retained coach-authored program;
  its provenance remains coach-authored. A new coach gains program authority
  only when that coach publishes a program.
- A coach may disable coaching without deleting their own player data. This
  ends their assignments and restores program authority to affected players.

### Privacy
- Player↔assistant chat history is **never** exposed to coaches.
- Hosted AI processing is disclosed before use. Coach model prompts omit player
  names, contact details, and player-assistant chat; both models receive only
  the context needed for the request. User-written free text may still contain
  identifying information.
- During an active assignment, coaches see workouts, telemetry, PRs, alerts,
  and earlier training history. Revocation ends that access immediately.
- A shared check-in record remains in the player's history after unassignment;
  the former coach loses access. After coach account deletion, its attribution
  reads "former coach."
- Directory exposes only coach-authored fields — no rosters, client counts, or
  computed stats.
- Play disclosures accurately describe coach access to player training data.

## 3. Assignment Model

Two consent paths:

| | Invite code (default) | Directory (opt-in) |
|---|---|---|
| Coach exposure | None — invisible | Only coach-authored fields |
| Initiator | Coach invite, accepted by player | Player request |
| Binding | Single-use code: instant after explicit player consent | `requested → approved/rejected → active` |
| Availability | Closed trial | After the closed trial; opt-in only |

- Before redemption, show the player the coach's identity and the exact
  training-history access being granted. The coach authorizes the first
  redeemer by issuing a code; the player must explicitly consent. A forwarded
  or stolen unredeemed code can therefore bind a different player. Codes expire
  quickly; the coach receives an in-app and email notice on redemption and may
  revoke the assignment immediately. The email contains no training data.
- For the later directory path: one pending outbound request per player,
  request rate limit (3/hour), coach-side block list, and capacity shown as
  available/full. `discoverable` defaults to `false` when discovery opens.
- All invite codes are single-use, expire, and are bounded by roster capacity.

## 4. Why This Is Feasible (Architecture Evidence)

- The Streamlit UI is a pure HTTP+SSE client (`ui/api_client.py`); the FastAPI
  service layer already provides a player contract with JWT auth, rate limits,
  and anti-enumeration. The coach contract and dual-capability identity are new.
- Model construction uses the `get_llm()` / `get_judge_llm()` /
  `get_coach_llm()` factories behind a LangChain-standard surface. The cloud
  factory exists in the current worktree; live chat and onboarding inference
  still need to be covered by the promised concurrency limit.
- The eval harness (`tests/eval/run_evaluation.py`) uses the same factories, so
  the existing 65-case + 15-case suites can check the player model swap. The
  command still needs a failing exit status when thresholds are missed.
- The deterministic temporary program exists (ADR-011); coach provenance,
  mutation authority, and expected calendar days are additional concepts.
- The "performance degraded / deload detected" alarm is the existing ADR-004
  progression signal, persisted as a coach-facing event instead of only
  surfacing in the player debrief.
- Cross-user state has a proven home: the ADR-007 pattern (catalog-side storage
  for concerns that cannot know which ledger to open) extends directly to
  roster summaries and alert events — coach list views never open ledgers.
- SQLite online backup (3+1 retention, ADR-005) and config-driven SMTP email
  (ADR-007) already exist; R2 and Resend are additive.

## 5. Phases

### Phase 0 — LLM Backend Abstraction

1. **Factory swap** — `utils/model_downloader.py`
   - Env `LLM_BACKEND` = `local` (default) | `openai`.
   - `openai` → thin `SafeChatOpenAI` wrapper (langchain-openai `ChatOpenAI`):
     `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` (Qwen3.5-9B player),
     `temperature=0.0`, `max_tokens=200`, streaming. Judge equivalents
     (`JUDGE_MODEL`, Qwen3.5-27B, `max_tokens=700`) and coach equivalents
     (`COACH_MODEL`, Qwen3.5-27B) follow the same shape.
   - **Thinking mode disabled at API level** via
     `extra_body.chat_template_kwargs.enable_thinking=false`. The live smoke
     verified the model echo, non-reasoning response, streaming, and tool calls.
     `CoachOutputScrubber`
     (`utils/text_scrubber.py:38`) remains the final guard.
   - Mock seams preserved: `TESTING=1` → `MockSafeChatLlamaCpp` regardless of
     backend; `openai` + missing key in pytest context → mock.
2. **Concurrency** — `svc/llm.py`
   - `LLM_MAX_CONCURRENT` bounds chat streams and onboarding invocations in
     the current service paths. Keep the trial default at 1 until load testing
     the single SQLite writer.
   - Meter hosted-model usage per account, enforce separate player and coach
     request limits, and alert the owner when projected monthly spend reaches
     $50. Review measured usage before expanding the trial.
3. **Parity gate (blocking)**
   - `pytest` full suite green (mock path, zero regression).
   - Provider smoke passed for Qwen3.5-9B: model ID, thinking-off, streaming,
     and tool calls. The proposed Qwen3.5-4B endpoint was unavailable.
   - 65-case standard + 15-case generalization suites with
     `LLM_BACKEND=openai` (player = Qwen3.5-9B, judge = Qwen3.5-27B).
     **Gate: ≥ 62/65, 15/15 generalization, strict 5/5 clinical safety.**
     The measured runs scored 62/65 and 15/15 with no clinical-safety failures.
     The eval command exits nonzero below the gate.

### C1 — Coach Domain & Authorization

- **Catalog schema** (ADR-007 pattern): durable account registry with
  immutable account IDs, reusable usernames, capabilities, and deletion/session
  state; `coaches` (profile + capacity),
  `coach_invite_codes` (hashed, TTL, single-use), `coach_players`
  (assignment + status state machine + consent + revocation),
  `player_summaries`, `alert_events`. Add `discoverable` and `coach_blocks` with
  the post-trial directory.
- **Ledger schema v6**: `training_programs` gains program provenance and
  coach-publication state (lazy migration, ADR-005); stable program versions and
  exercise-slot identities support substitution requests and offline logs.
  Provenance and current mutation authority remain distinct after unassignment.
- **Auth**: authorize the account's current capabilities via the durable
  registry; every coach→player access additionally requires an active
  `coach_players` row. JWT `sub` is the immutable account ID, never a reusable
  username; check the durable account status, capabilities, and session epoch
  before opening a ledger. A singular `role` claim cannot represent
  dual-capability accounts. Player-side unassign path.
- **Registration**: player capability on a new or existing account; coach
  capability only by owner invitation in the closed trial. Player registration
  accepts an optional single-use coach invite. Directory endpoints are
  reserved for after the trial. Keep legacy `trainee` API names where
  compatibility requires them; use `player` for new domain and product names.
- **Coach accounts**: a coach who trains uses the same account and workout
  ledger; account deletion follows the same lifecycle for both capabilities.
- **Lifecycle semantics**:
  - Coach unassign / revocation → the player **keeps the assigned program
    content** while self-service mutation authority returns; preserve its
    coach-authored provenance; in-app notice; active alerts for that pairing
    closed. Shared check-ins remain in the player's history, and former-coach
    access ends.
  - Coach capability disabled → all of that coach's assignments end with the
    same revocation behavior; the account's own player data remains.
  - Coach account deletion → all assigned players keep their assigned programs
    with self-service authority restored (notified); `coach_players` rows and
    pending requests purged. Retained shared check-ins show "former coach"
    instead of the deleted coach's identity.
  - Player account deletion → removed from roster; alert/pending-request rows
    purged; ledger and user-specific backups removed (see Phase D).
- **Rate limits** for coach endpoints.
- **Invite redemption**: short-lived code, atomic one-use claim, capacity check,
  coach-block check, and explicit player acceptance precede immediate
  assignment. No recipient verification is required. Notify the coach in-app
  and by email, without training data in the email; allow immediate revocation.

### C2 — Alert Engine (fully deterministic, zero LLM)

- Signals: **follow-up due** (per-player check-in cadence, default weekly),
  **2+ consecutive expected-day skips** (expected weekdays from the player's
  explicit weekly schedule, excluding schedule pauses; 24-hour local-time grace;
  one workout satisfies at most one expected day, earliest eligible unmet day
  first; streak-transition firing so one absence never re-alarms daily),
  **deload/regression detected** (hook existing ADR-004 triggers at
  `commit_session` in `service/workouts.py`).
- New non-LLM profile fields: **player timezone**, expected training weekdays,
  and schedule pauses (collected explicitly, never LLM-parsed). Program day
  order alone does not establish attendance expectations. Players may set a
  future pause of up to 14 days without giving a reason; dates are visible to
  the coach and trigger a notice. Pauses cannot erase earlier misses.
- Attendance uses workout performed dates, not entry timestamps. Schedule
  changes apply prospectively; performed dates may be entered or corrected up
  to three days back. Preserve upload/edit timestamps, show corrections to the
  assigned coach, and recalculate affected absence alerts.
- A dated coach check-in record represents contact inside or outside MAYOS and
  resets the weekly follow-up clock. Both coach and player see its date,
  contact channel, and optional short note.
- Trigger points: session commit (event-driven) + daily sweep for absences and
  follow-ups. The sweep is invocable as a script for dev/tests; production runs
  it on the single API Machine with an idempotent durable last-run marker.
- Storage: catalog-side `alert_events` with statuses (`new`, `acknowledged`,
  `resolved`); a corrected workout log can resolve an inaccurate absence alert.
  `player_summaries` updated at commit + sweep → roster reads never open
  ledgers.

### C3 — Coach API Surface

- `GET /coach/roster` (summaries + alert badges; catalog-side).
- `GET /coach/players/{id}/sessions|volume|history|prs` (existing service
  functions behind coach authz).
- `POST /coach/players/{id}/program` (assign split — deterministic generator
  with coach-selected parameters).
- Coach-only substitution operation updates a coach-controlled program. A
  player substitution request enters a coach queue without changing the
  program; coach action closes the request and notifies the player. Requests
  identify the exact program version, day, and exercise slot, with the desired
  replacement and reason. Revalidate the slot before applying a stale request.
  Request states are `pending → applied / declined / cancelled`; a decline
  includes a short player-visible response. New requests send a generic email
  and in-app notice to the coach, without training detail in email.
- `GET /coach/alerts` + ack · invite-code endpoints · check-in recording ·
  split-change and substitution-request queues. Directory assignment requests
  follow the trial.
- Player-side: all program write paths, including exercise substitutions,
  redirect to request creation after the first coach-authored program is
  published.
- Workout logging accepts skipped and unplanned performed exercises as facts
  without treating them as program substitutions; such divergences appear in
  the assigned coach's view.
- Split assignment raises an in-app notice on the player side (program changed
  by coach).

### C4 — Coach Assistant (conditional; does not block the initial trial)

- Use the coach model config already present in the factory (`COACH_LLM_*`).
- Scope: player-scoped telemetry analysis + split help, with names, contact
  details, and player-assistant chat excluded from prompts. Zero-drift philosophy
  preserved — telemetry math and split assembly stay deterministic
  (ADR-003/011); the 27B writes analysis prose and answers Q&A over a player
  telemetry snapshot (the snapshot pattern already exists for the player
  assistant).
- `/coach/chat/messages` SSE, mirroring `svc/routers/chat.py`. In the trial,
  coach-assistant conversation context stays in memory for one selected player
  and is cleared on player switch, revocation, logout, or app close; no
  coach-assistant transcript is persisted by the service.
- New small eval suite for the coach assistant (the 65-case suite only
  validates the selected player model).
- Explicit coach-chat rate limit (e.g., 15/min, separate from the player's
  `CHAT_LIMIT`) — the 27B is the most expensive surface in the system.

### Phase D — Hardening, Backups & Deployment

- **Public-API hardening**: `ALLOWED_HOSTS` env driving
  `TrustedHostMiddleware` (`svc/app.py:65`); HTTPS via Fly anycast TLS.
- **Account deletion** (`DELETE /auth/account`, both capabilities): password
  confirmation → durable registry invalidation of all sessions → coordinated
  ledger/WAL deletion → purge catalog relationships and user-specific local/R2
  backups. A later registration may reuse the username only with a new account
  ID. Restores must not resurrect deleted identities. Applies the C1 lifecycle
  semantics.
- **Reset-link UX**: change `build_reset_link` (currently
  `/?reset_token=…`) to the production Android App Link
  (`https://<domain>/reset?token=…`); a hosted page handles the not-installed
  fallback. Setting `UI_BASE_URL` alone does not change the path.
- **Backups**: a daily job on the single always-running API Machine uses SQLite
  online backup across ledgers + catalog → R2 via boto3. The sweep and backup
  jobs have durable last-run markers and are safe to retry after restart.
  Active-account snapshots have up to 30-day retention;
  account deletion removes user-specific copies. Restricted whole-catalog
  recovery backups may retain deleted rows for up to 30 days, disclosed in the
  privacy policy. A durable deletion record outside the restored snapshot must
  be replayed on every restore.
  A separate scheduled Machine cannot mount the API Machine's
  [volume](https://fly.io/docs/volumes/overview/). Disable autostop so idle
  periods do not skip jobs, and disable Fly's
  [default volume snapshots](https://fly.io/docs/volumes/snapshots/).
- **Existing-user import**: offer an opt-in, audited import for identified real
  users only. Create new immutable account IDs, use a secure claim path for
  users without existing credentials, take consistent SQLite snapshots, and
  verify imported record counts. Never bulk-import local development ledgers.
- **Email**: Resend SMTP credentials + SPF/DKIM on the domain (transport
  already exists); add invite-redemption and program-request notice templates.
- **Deployment**: `Dockerfile.fly` (`python:3.12-slim`, install without
  `llama-cpp-python` — split `requirements.txt` into base + `[local-llm]`
  extra, `MODEL_DEVICE=cpu`, CMD `uvicorn svc.app:app --workers 1`,
  healthcheck `/healthz`); `fly.toml` (single machine, `fra`, 1–2 GB, 10 GB
  volume at `/data`, autostop off); route catalog, ledgers, and local backups to
  the mounted volume; one-time catalog init + vector seeding; secrets via
  `fly secrets set`.
- **Spend guard**: meter model requests/tokens by account and model, apply
  per-account rate limits, and send an owner alert at $50/month projected spend.
  The original $15–20 estimate is not a release budget or a verified forecast.

### C5 — Flutter Product Client (`mobile/`)

- **Workout sync contract**: extend workout commit with a stable client session
  ID, performed date/timezone, and captured program version. Commit session,
  sets, and derived records atomically or recoverably; repeat delivery of the
  same client ID returns the same outcome. Provide status/reconciliation for a
  lost response. If the coach publishes a newer program before sync, accept the
  workout as history against the captured version, show the version difference
  to both parties, and leave the new program unchanged. A revoked assignment
  cannot grant the former coach access to the eventual sync.
- Layout: `features/player/`, `features/coach/`, `features/shared/` — clean
  package boundaries so extracting a second app or a web coach console later is
  cheap.
- Stack: Riverpod, `dio` (+ auth interceptor, 401 → re-login),
  `flutter_secure_storage` (JWT → Android Keystore), `drift` (player read cache
  and workout drafts),
  `go_router` (capability-gated navigation), OpenAPI → Dart client from
  `/openapi.json`.
- SSE: streamed dio parsing of `token` / `done` / `error` frames (mirror
  `ui/api_client.py:104`).
- **Player**: auth (login/register/remember-me/forgot/reset), invite-code entry,
  onboarding, dashboard (volume + PR shelves), offline-capable workout logger,
  program (+ xlsx share),
  chat, debrief, settings (persona, change-password, request split or exercise
  substitution, unassign coach, account deletion).
- **Coach console**: roster with alert badges, player drill-down (sessions,
  telemetry, history), alert center, split assignment, check-in recording,
  split-change and substitution-request queues, profile editor. Coach chat is
  enabled only after
  its privacy and eval gates; its transcript is in memory for the current
  player/session only. Directory controls follow the closed trial.
- Offline: player dashboard/history/program use a read cache; the workout
  logger persists drafts locally and syncs them on reconnect with visible
  pending/synced/conflict state. Unsynced drafts survive app restart and logout
  in protected per-account storage; logout warns about them and offers an
  explicit discard action. Account deletion erases drafts on the deleting
  device; other offline devices erase them when they next check account status.
  Coach console, chat, and program changes require connectivity. The coach
  console is online-only in the trial.
- **Legacy UI retirement**: remove Streamlit app, UI transport, and associated
  dependencies after the four-week trial passes its exit gates and opted-in
  real-user imports finish, before public launch. Retain service-layer and
  engine tests independent of Streamlit.
- **Trial communication**: coach and player communicate outside MAYOS.
  Shared check-in records and program-change requests capture the relevant
  actions; direct in-app coach-player messaging is outside the trial.

### Phase P — Google Play Compliance

- Privacy policy URL and in-app access to that policy; accurate data-safety
  form covering coach and hosted model data access; in-app account deletion for
  both capabilities **and** an
  [external deletion-request URL](https://support.google.com/googleplay/android-developer/answer/13327111)
  in Play Console;
  Play app signing. The trial is free and invite-only. Before opening directory
  discovery or payments, at least five pairs complete four weeks; each coach
  publishes a program and records two check-ins; there is no unauthorized
  access or data loss; and account deletion plus restore drills pass. Assess
  usefulness separately through interviews.

## 6. Closed-Trial Verification Gates (in order)

1. `pytest` green on mock backend (zero-regression baseline)
2. Hosted-provider curl smoke (model IDs + thinking-off + tool calls verified)
3. Player eval suites ≥ 62/65 and 15/15 on the selected hosted backend
4. Authorization tests (C1): coach can only open actively assigned player
   ledgers; revoked assignments denied; dual capabilities enforced; every
   program write path, including existing exercise-swap routes, respects coach
   authority; stale or ambiguous substitution requests cannot change the wrong
   slot; old tokens cannot recreate deleted accounts
5. Alert engine unit tests (C2): timezones, 24-hour grace, prospective schedule
   changes, three-day late entries/corrections, one-workout-per-expected-day
   matching, pause visibility, streak dedup, check-in cadence, deload transition
6. Workout sync tests: offline draft reconnect, duplicate retry, lost response,
   performed date/timezone, historical-version acceptance, revocation before
   sync, logout/account isolation, deletion cleanup, and atomic/recoverable
   session plus sets; unplanned logs do not mutate the program
7. Phase D deploy: `/healthz` + `/readyz`, register/login/chat SSE over HTTPS,
   password-reset round-trip, account-deletion round-trip, per-account model
   limits, and projected-spend alert
8. Flutter trial path e2e: player register → onboard → log → chat → request
   split; invited coach enables capability → issues single-use invite → assigns
   program → handles substitution request → records check-in → handles alert →
   drills down; player records an offline draft and syncs it; revoke and delete
   account. Coach capability deactivation preserves that person's own player
   data. Test a consented import of one identified real user's local history
   before cutover.

Coach-assistant activation has its own gate: privacy review and a new eval
suite pass; player-switch, revocation, logout, and app-close context clearing
are verified. Directory flow is tested after the trial, before discovery opens.

## 7. Known Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Hosted Qwen drift vs local Q4_K_M (player) | Phase 0.3 parity gate; choose a verified provider/variant before pricing or release |
| Proposed DeepInfra 4B endpoint was unavailable | Use the verified 9B player model for the trial; recheck availability only if changing models |
| Coach 27B has no baseline | Dedicated small eval suite before ship (C4) |
| Cross-ledger authz flaw | Assignment-gated dependency + explicit authz test gate |
| Cross-ledger aggregation pressure | Catalog-side `player_summaries` / `alert_events`; roster never opens ledgers |
| Alert edge cases (TZ, deload weeks, streak dedup) | Deterministic, fully unit-tested engine |
| Thinking tokens eat the 200-token budget | Disable at API level; scrubber as final guard |
| Single-replica SQLite ceiling | Documented wall; Postgres/Litestream is the future path |
| Relationship/privacy abuse | Mutual consent, block list, request rate limits, private chat |
| Forwarded unused invite code | Short expiry, single-use atomic redemption, coach identity and access disclosure, immediate coach email/in-app notice and revocation |
| Player bypasses coach program control with an exercise-swap path | Gate all program writes centrally; player request cannot mutate a coach-controlled program |
| Offline retry duplicates or misdates a workout | Stable client ID, performed date/timezone, program version, idempotent commit, and reconciliation status |
| Coach changes program before offline sync | Preserve historical program version on the workout; flag difference; never rewrite the new program |
| Local development ledgers mistaken for real users | Explicit opt-in import only for identified real accounts; audited record counts and secure claim |
| Play policy rejection | In-app and external deletion paths, in-app privacy policy, and accurate data-safety form |

## 8. Prerequisites (Owner Actions)

- [ ] Hosted player-model provider account + API key; verify candidate model,
      non-reasoning behavior, tool calls, cost, and parity gate
- [ ] DeepInfra account + API key if using its coach and judge models; verify
      exact model IDs and the thinking toggle
- [ ] Fly.io account
- [ ] Production domain (API URL, App Links, SPF/DKIM)
- [ ] Resend account
- [ ] Cloudflare R2 bucket + credentials
- [ ] Identify any real local users who want an opt-in history import; exclude
      development/test ledgers

## 9. Operating Cost Inputs (< 100 users; verification pending)

| Item | Cost |
|------|------|
| Fly.io machine + volume | Verify for always-on 1–2 GB Machine and 10 GB volume |
| Hosted player LLM (~4–5 M tokens/mo) | Unverified until model and price are confirmed |
| DeepInfra coach LLM (27B, low-frequency) | Verify after measured usage |
| DeepInfra judge (per eval run) | Verify after eval run |
| R2 storage | Verify after backup-size estimate |
| Resend SMTP | Verify current tier and expected mail volume |
| **Total** | **To be recalculated after model, usage, and Fly configuration are verified** |

Alert the owner at $50/month **projected** spend during the closed trial;
apply per-account model rate limits and review actual usage before expanding.

## 10. Deferred Work

- **Coach directory**: after a successful trial, add opt-in discovery
  (`GET /coaches`, `POST /coaches/{id}/request`), coach approve/reject/block,
  and the directory assignment path. Test the full request → approval flow
  before enabling discovery.
- **Monetization**: closed trial is free; decide who pays (coach subscription
  via Play Billing vs. paid listing vs. freemium) before a paid/public launch.
- **Push notifications (FCM)**: deferred to v2 — v1 ships the in-app alert
  center only.
- **Multiple coaches per player**: deferred to v2+.
