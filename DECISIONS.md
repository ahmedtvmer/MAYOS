# Architecture Decision Records (ADRs) & Engine Safeguards

This document records the architectural, algorithmic, and heuristic decisions implemented in the MYOS engine.

---

### ADR 001: Hypertrophic Frequency Clamping (1–5 Days)
* **Status**: Accepted
* **Rule**: The onboarding intake graph rejects requested training frequencies > 5 days/week and clamps split generation strictly to 1–5 days per microcycle.
* **Context**: Trainees frequently request 6- or 7-day splits. Generating high-frequency routines via edge models often produces overlapping movement patterns with inadequate recovery between identical muscle groups.
* **Rationale**: **Internal Coaching Heuristic & Safeguard.** Natural trainees training with genuine proximity to failure (0–3 RIR) require sufficient recovery capacity between high-tension sessions. Enforcing a 5-day ceiling guarantees at least two non-training recovery days per microcycle, maintaining systemic recovery without relying on the LLM to balance complex 6-day split distributions.
* **Code References**: `agent/onboarding_graph.py` (`STEP2_SEGMENT_RE`, `weekly_frequency` validator).

---

### ADR 002: Multi-Tier Clinical Safety Intercept
* **Status**: Accepted
* **Rule**: Split safety evaluation into Tier 0 (Fast-Path Regex, <0.02 ms) and Tier 1 (BGE-small Semantic Cosine Guard, ~15 ms at threshold >= 0.70), while bypassing physiological fatigue terms (e.g., metabolic burn, quad exhaustion). Tier 0 is itself split: Tier 0a is unconditional (sharp pain/pop, shooting/radiating pain, numbness, tingling, pinched nerve, hernia, dislocation, cannot-move, joint clicking with pain); Tier 0b context-gates the DOMS-ambiguous tokens (swell/swollen, tear/tore/torn, pop, tweaked) so they intercept only with mechanism perception ("felt/heard a pop"), anatomical-structure proximity (joints, tendons, pec/bicep/ACL, ...), or body-part objects. DOMS idioms ("torn up", muscle-group swelling "from leg day", "tweaked my program", painless "knees pop when") defer to Tier 1.
* **Context**: Human trainees describe musculoskeletal damage colloquial-first ("velcro tearing", "hot glass in joint", "pins and needles"). Keyword-only regex creates false negatives, while evaluating full LLM prompts on every message introduces CPU thermal throttling and multi-second latency.
* **Rationale**: **Defensive Safety Architecture.** Acute musculoskeletal trauma demands an immediate halt. Combining deterministic token matching for common trauma terms with an in-memory 8-anchor semantic cosine guard catches edge-case somatosensory feedback while allowing normal hypertrophic fatigue to reach the coaching prompt.
* **Code References**: `agent/clinical_guard.py` (`evaluate_clinical_semantic_guard`), `agent/assistant_graph.py` (`router_node`, `_acute_injury_hit`, `RE_AMBIGUOUS_TRAUMA`).

---

### ADR 003: Deterministic Post-Workout Debrief Synthesis
* **Status**: Accepted
* **Rule**: Post-workout debriefs assemble **Overload Deltas**, **Fatigue & CNS Check**, and **Next Session Directives** deterministically in Python rather than generating them via free-form LLM inference.
* **Context**: Quantized 3B models under CPU load suffered from instruction drift, omitting deload directives in 40% of generalization test cases and introducing non-deterministic progression advice.
* **Rationale**: **Zero-Drift Engineering.** Analytical calculations (e1RM, volume load, load increments, fatigue states) are mathematical, not probabilistic. Assembling the response deterministically guarantees 100% deload compliance, eliminates hallucinatory load increases, and reduces CI debrief evaluation time from ~14 minutes to single-digit milliseconds.
* **Code References**: `agent/debrief.py` (`generate_session_debrief`).

---

### ADR 004: Systemic Fatigue Floor & Reactive Deload Triggers
* **Status**: Accepted
* **Rule**: A reported readiness score of 1/5, an acute readiness collapse, or sustained high exertion density triggers an immediate reactive deload: a 50% session volume cut and a mandatory RPE 7.0 ceiling (minimum 3 RIR).
* **Context**: Allowing progressive overload or RPE 9–10 top sets under acute systemic exhaustion or unrecovered joint strain sharply elevates soft-tissue injury risk.
* **Rationale**: **Internal Coaching Heuristic (Auto-regulation).** While general tapering literature indicates volume reductions between 30% and 70% dissipate fatigue while preserving adaptation, the specific combination of a 50% set cut and an RPE 7.0 cap is an auto-regulatory heuristic. Halving working sets cuts mechanical accumulation, and capping intensity at RPE 7.0 prevents failure-induced strain while reinforcing motor patterns.
* **Code References**: `agent/progression_engine.py` (readiness and deload evaluation), `agent/prompts.py` (`STATIC_SYSTEM_CORE`).

---

### ADR 005: Lazy Per-User Schema Migrations & Atomic Snapshotting
* **Status**: Accepted
* **Rule**: Per-user databases (`db/users/<id>.db`) migrate lazily upon connection mount in `DatabaseManager.switch_user()`. Version state is tracked using `PRAGMA user_version`. Backups use `sqlite3.Connection.backup()`, enforcing a 3+1 retention policy (3 rolling session backups + 1 immutable pre-migration snapshot).
* **Context**: SQLite `CREATE TABLE IF NOT EXISTS` cannot alter tables or handle schema evolutions. Eager migrations on engine boot degrade startup performance with large user directories, and raw file copies during WAL execution risk file corruption.
* **Rationale**: **Local-First Resilience & Zero-Downtime Snapshots.** Using SQLite's native online backup API flushes active WAL frames into a consistent snapshot while transactions remain open. Lazy execution bounds startup time to $O(1)$ relative to total users. If a migration fails mid-stream, the engine executes an atomic rollback from the pre-migration snapshot.
* **Code References**: `database/migration_manager.py`, `database/database_manager.py` (`switch_user`, `create_user_schema`).

---

### ADR 006: Token-Version Session Epoch (Revoke-All on Password Change)
* **Status**: Accepted
* **Rule**: Per-ledger `auth_credentials.token_version` (schema v3) is stamped into every JWT as the `tv` claim at issue time (`register`/`login`/`claim`). `get_current_trainee` rejects any token whose `tv` differs from the ledger's current version with the same 401 as a revoked `jti`. `change_password`, email `reset_password_with_token`, and the admin CLI all `bump_token_version()`, killing every session including the caller's.
* **Context**: Revocation was per-`jti` only (`revoked_tokens`), so a password change left all other sessions alive — exactly the sessions an account-takeover victim needs dead. Enumerating live `jti`s per user was never stored, making "revoke all" inexpressible.
* **Rationale**: **Fail-closed session invalidation.** A single monotonic epoch per ledger expresses "all tokens before X are dead" in O(1) without a session table. Pre-v3 tokens without `tv` read as version 1, so rollout is backwards compatible until the first password event bumps the epoch. Change-password failures return 400 (never 401) so clients don't misread "wrong current password" as session expiry.
* **Code References**: `database/migration_manager.py` (`_migrate_v2_to_v3`), `database/database_manager.py` (`get_token_version`, `bump_token_version`), `svc/auth.py` (`create_access_token`, `token_version_of`), `svc/dependencies.py` (`get_current_trainee`), `service/auth.py` (`change_password`), `svc/routers/auth.py` (`change_password`).

---

### ADR 007: Catalog-Side Recovery Identity & Single-Use Reset Tokens
* **Status**: Accepted
* **Rule**: Recovery emails (`trainee_emails`) and reset tokens (`password_reset_tokens`) live in the **shared catalog DB**, not per-user ledgers, because the logged-out forgot-password flow cannot know which ledger to open. Tables are provisioned at catalog boot (`ensure_account_schema()` outside any held lock). A recovery email is **mandatory**: after login, a minimal gate page (Logout only) blocks dashboard and onboarding until one is saved; onboarding email is collected there, never parsed by the LLM. Tokens are `secrets.token_urlsafe(32)` with only the SHA-256 stored, TTL 30 min (env `RESET_TOKEN_TTL_MINUTES`, clamped 5–120), single-use via atomic `used_at` claim, and redemption bumps `token_version`. Both endpoints are anti-enumeration: `forgot-password` returns the identical 202 message for known/unknown emails, and unknown/expired/used tokens share one 400 error. Strict `3/hour` rate limit; SMTP optional with a console-dev backend (`SMTP_HOST` unset logs the link server-side). The UI transport helper `request_json()` never raises and never calls `st.stop()`, so malformed/HTML/timeout responses surface inline instead of blanking the page.
* **Context**: Ledgers are keyed by trainee_id with no contact channel; classic email reset had no identity to address and no table reachable while logged out. Per-ledger token tables would require scanning every `db/users/*.db` per request.
* **Rationale**: **Local-first compatible recovery.** Catalog-side storage keeps lookup O(1) and lets the admin CLI (`scripts/reset_password.py`) remain the no-email backstop with identical revoke-all semantics. Storing hashes (never raw tokens) and constant-shape responses preserves the existing indistinguishable-credentials posture from `service/auth.py`.
* **Code References**: `database/database_manager.py` (`ensure_account_schema`, `consume_reset_token`, …), `service/password_reset.py`, `service/email_sender.py`, `svc/routers/auth.py` (`forgot-password`, `reset-password`, `email`), `scripts/reset_password.py`, `ui/api_client.py` (`request_json`), `ui/views/auth.py` (`render_email_gate`), `app.py` (post-login gate).

---

### ADR 008: Hardened Local Model Lifecycle (Atomic Download, Explicit Test Mode)
* **Status**: Accepted
* **Rule**: GGUF downloads take a cross-process file lock, re-check under the lock, clean up zero-byte partials, and verify an optional pinned SHA-256/revision (`MODEL_SHA256`, `MODEL_REVISION`); logging replaces `print`. Test doubles engage on explicit `TESTING`/`SKIP_LLM_LOAD`/`CI`, plus a pytest-only fallback **iff the model file is absent** — a test run can therefore never trigger a multi-GB download. Lazy proxies no longer load on dunder/repr access, and the judge shares `SafeChatLlamaCpp` (tool-call dedup) with its own mock branch (previously it always pulled the 9B GGUF, even in CI).
* **Context**: The loader used an import-time stale path, a `threading.Lock` that can't stop multi-worker OOM, string-matched `ValueError`s, hardcoded `n_ctx`/`max_tokens`, and `"pytest" in sys.modules` detection that flipped production behavior whenever pytest was merely installed.
* **Rationale**: **No-surprise edge inference.** Every change removes a class of startup/OOM flakiness while keeping the public surface (`get_llm`, `get_judge_llm`, `llm`, `judge_llm`) stable; inference tuning is now env-overridable (`LLM_N_CTX`, `LLM_MAX_TOKENS`, `LLM_THREADS`, honoring `OMP_NUM_THREADS`).
* **Code References**: `utils/model_downloader.py` (`_file_lock`, `_should_use_mock`, `_attach_prompt_cache`, `_LazyLLMProxy`).

---

### ADR 009: Deterministic Personal Record Detection (Exact-Rep + e1RM)
* **Status**: Accepted
* **Rule**: After every session batch insert, `evaluate_session_prs` reduces the working sets to the heaviest set per exact rep count plus the best-e1RM set and records only values that **strictly exceed** the trainee's historical max (ties are never PRs). Two record types are stored append-only in `personal_records`: `max_weight` scoped to the exact rep count (heaviest 5-rep set) and `max_e1rm` exercise-wide. At most one row per record type per movement per session is written. Warmup-flagged, zero-load, and zero-rep sets are ignored. Migration v3→v4 creates the table and backfills history with first-achievement timestamps. The `🏆 New PR` lines are injected deterministically into the debrief's Overload Deltas block and the dashboard renders global + per-movement PR shelves; no LLM is involved anywhere in the path.
* **Context**: e1RM was already computed per set for overload deltas, but PRs were never detected, so the ledger could not answer "is this my best 5?" — and forward-only recording would have set trivially-true PRs on the first post-ship session against an empty table.
* **Rationale**: **Zero-Drift Engineering + motivation loop.** Exact-rep brackets mirror how lifters actually benchmark (a 3-rep and a 5-rep max are different achievements), while strict-greater comparison keeps the ledger stable under ties and re-logged sessions. Backfill-on-migration (ADR 005) makes the timeline truthful from day one without a new dependency or LLM surface.
* **Code References**: `agent/progression_engine.py` (`check_and_record_pr`, `evaluate_session_prs`), `service/workouts.py` (`commit_session`), `agent/debrief.py` (`format_pr_events`), `database/migration_manager.py` (`_migrate_v3_to_v4`), `service/dashboard.py`, `svc/routers/dashboard.py` (`/dashboard/personal-records`).

---

### ADR 010: Consented Remember-Me Cookie Sessions
* **Status**: Accepted
* **Rule**: The Streamlit client persists the bearer JWT in a browser cookie (`mayos_jwt`) only after the trainee ticks "Remember me on this device" on login/register. Remembered tokens are minted with `JWT_REMEMBER_ME_HOURS` (default 720 h = 30 days, clamped 1–8760); the default 2-hour token path is unchanged. On boot the client hydrates session state from the cookie (unverified `sub` read for display/gating only — every API call still sends the bearer for server-side verification); invalid or expired tokens fall through to the existing 401 clear-and-flash flow. Logout and any 401 clear the cookie. All cookie operations are best-effort: without the component the app behaves exactly as before.
* **Context**: A browser refresh starts a fresh Streamlit websocket session, wiping in-memory state, so trainees were bounced to the login page on every refresh; the 2-hour default TTL compounded it, and no persistence mechanism existed.
* **Rationale**: **Local-first convenience without weakening server authority.** The cookie is a client-side memory of the same revocable JWT — ADR 006 `tv` epoch bumps and `jti` logout revocation still apply instantly — and consent is explicit. Storage is a plain (non-HttpOnly, SameSite=Lax, Path=/) cookie on the Streamlit origin because the FastAPI service is only ever called server-side by the UI process; the browser never talks to the API directly. Degradation is safe by construction (every cookie operation wrapped).
* **Code References**: `ui/cookies.py`, `ui/session.py` (`restore_auth_from_cookies`, `establish_session`), `ui/views/auth.py`, `app.py`, `svc/auth.py` (`remember_me_hours`), `svc/routers/auth.py` (login/register/claim), `svc/schemas.py` (`TraineeIn.remember_me`).

---

### ADR 011: Movement-Slot Blueprints as the Program Generation Unit
* **Status**: Accepted
* **Rule**: Program assembly is driven by ordered **movement slots** per day (`incline_press`, `horizontal_row`, `biceps_preacher`, `forearm_wrist`, `adductors`, ...), not one-exercise-per-muscle. `agent/program_blueprints.py` owns the slot SQL patterns/equipment preferences, prescriptions (warm-up sets 0–4, working sets 1–4, rep windows, 2–5 min rests), general warm-up blocks (Pallof/scapula push plus/glute bridge/dead bug/reverse hyper) and the split day templates. Working sets come from `slot_working_sets()`: compounds carry 2 sets, isolations 1, escalating to 2 only where the references did (leg staples on lower/female days, arm/delt isolations on arm days); full-body days run a minimal profile (2 sets on the day's `double_slots` priority lifts + calves only). `agent/program_rules.py` resolves slots against the catalog (word-boundary exclusions, name-pattern and equipment ranking) and routes split preferences deterministically (Full Body, Upper/Lower, Arnold, Arnold x U/L, Anterior/Posterior, PPL, female glute-biased). Keyword routing is word-boundary strict so body-part phrases ("lower back pain", "upper chest focus", "posterior chain") never hijack the router; a recognized keyword at an unsupported frequency falls back to the deterministic frequency default instead of the LLM; and Arnold requests at 4–5 days map onto the Arnold x Upper/Lower hybrid pool (the reference 5-day sample shape). All program output is **English-only and free of reference-author phrasing**: generated `notes` carry the exercise catalog's own step-by-step execution text (shown in the Form Demos panel), swapped exercises store the replacement's catalog steps, and the program-level instruction blocks were removed entirely — execution guidance is delegated to the coaching assistant and the demos. The xlsx export uses an English column layout (Day, Exercise, Warm-up Sets, Working Sets, Reps, RPE, Rest, W1–W4 logging). Stated training goals modulate **only the cardio layer**: a fat-loss goal (word-boundary detection across `current_goal`/`long_term_goal`) prescribes a 20–30 min incline-walk/cycle finisher on every training day, while all other goals — including bulking — leave both cardio and the lifting program untouched; no lifting parameter reads the goal. Recovery signals (`stress_and_sleep`) modulate **only escalated-accessory volume**: poor sleep / high stress drops family-escalated isolation sets to 1 (capped at 4 sets per day; compounds, full-body priority lifts and calves keep theirs) while exercise selection, order and frequency never change. Limb proportions and mobility-only limitations are chat-context only; an injury filter that empties a slot (the back rule vs hinges) substitutes a safe fallback (`SLOT_FALLBACKS`) instead of silently shrinking the day.
* **Context**: Generated programs were fixed at exactly 5 exercises (one per hardcoded muscle target), almost never selected direct biceps/triceps/forearm work, never included incline chest, shrugs, adductors or the front lat pulldown machine, and had no Arnold or anterior/posterior option. Root causes: 5-muscle presets, a `min(target)`/machine-first candidate ordering that buried cable/dumbbell movements, target vocabulary missing `forearms`/`adductors`/`traps`, and SQL `LIKE '%term%'` exclusions whose substrings silently killed valid movements (`reach` → preacher, `run` → crunch, `chin` → machine).
* **Code References**: `agent/program_blueprints.py` (`SLOT_SPECS`, `WARMUP_SPECS`, `DayBlueprint`, `slot_working_sets`, `build_split_days`), `agent/program_rules.py` (`fetch_slot_candidates`, `fetch_warmup_candidates`, `_is_excluded`, `_name_rank_sql`, `resolve_split`, `SYSTEM_SPLIT_PROMPT`), `agent/program_generator.py` (`assemble_deterministic_day`, `build_warmup_block`), `agent/ProgramState.py` (`WarmupExerciseSchema`, `ProgramExerciseSchema.slot_key/warmup_sets`), `database/migration_manager.py` (`_migrate_v4_to_v5`), `utils/exporter.py`, `tests/test_program_blueprints.py`.

---

### ADR 012: Dual Inference Backend (Local GGUF + Cloud OpenAI-Compatible)
* **Status**: Accepted
* **Rule**: Inference backend is selected by `LLM_BACKEND` — `local` (default, GGUF via `llama-cpp-python`) or `openai` (any hosted OpenAI-compatible endpoint, e.g. DeepInfra). A single factory serves all roles: `get_llm()` (hosted player, Qwen3.5-9B), `get_judge_llm()` (hosted eval judge, Qwen3.5-27B), and `get_coach_llm()` (coach, Qwen3.5-27B), selected from `CLOUD_MODEL_REGISTRY` with per-role env overrides (`LLM_MODEL`/`JUDGE_MODEL`/`COACH_MODEL`, `*_MAX_TOKENS`, `LLM_API_BASE`, `LLM_API_KEY`). The cloud model is a thin `SafeChatOpenAI` wrapper exposing the same LangChain surface (`invoke`/`stream`/`with_structured_output`/`bind_tools`). **Reasoning/thinking is disabled by default** (`enable_thinking: false` via `extra_body`) so the tight output budgets (200/700/512) are never consumed by chain-of-thought; `LLM_ENABLE_THINKING=true` opts back in and `LLM_EXTRA_BODY` (JSON object) overrides provider-specific quirks. A missing `LLM_API_KEY` **fails fast** at model build (`RuntimeError`), so boot warmup fails loudly and `/readyz` reports not-ready instead of a green service that 401s every call. Mock seams are preserved: `TESTING=1` forces `MockSafeChatLlamaCpp` on either backend, and `openai` with no key under pytest/CI mocks automatically. Cloud inference is thread-safe, so `svc/llm.py` skips the llama.cpp `_INFERENCE_LOCK` and bounds overlap with `LLM_MAX_CONCURRENT` (default 1). In local mode `get_coach_llm()` aliases the production model (no separate coach GGUF). The eval harness must be invoked as a script (`python tests/eval/run_evaluation.py`) for a cloud parity run: the hermetic `tests/conftest.py` guard pins `LLM_BACKEND=local` for the pytest suite regardless of the developer's `.env`.
* **Context**: The local-first engine shipped a single backend bound to a GPU/CPU GGUF. The Android/coach-platform delivery (ANDROID-PLAN.md) requires a hosted endpoint, but the project's identity is offline-first and its model behaviour is pinned by an empirical eval baseline (63/65 standard, 15/15 generalization) measured on the local Q4_K_M weights. A naive swap risked (a) breaking the default local path, (b) silently enabling Qwen3.5 reasoning mode and exhausting the 200-token budget, and (c) `.env` cloud settings leaking into unit tests that assert the local constructor path.
* **Rationale**: **Contained, reversible, eval-gated.** Keeping `local` the default preserves the offline product and zero-regression guarantee, while isolating cloud-specific behaviour (model IDs, thinking toggle, key handling) in one module. Fail-fast key validation converts a per-request 401 into a startup/readiness failure that operators can actually see. The `conftest.py` guard makes the suite deterministic against developer `.env` drift. The existing eval harness uses the same factories, so the local→cloud transition is gated by the same 65-case/15-case suite rather than a hand-wave.
* **Hosted trial gate (2026-09-23)**: Qwen3.5-9B passed the provider smoke, scored 62/65 standard and 15/15 generalization with the Qwen3.5-27B function-calling judge, and had no clinical-safety failures. The accepted hosted standard threshold is 62/65; the local 63/65 result remains a historical baseline.
* **Code References**: `utils/model_downloader.py` (`SafeChatOpenAI`, `CLOUD_MODEL_REGISTRY`, `DEFAULT_CLOUD_API_BASE`, `_llm_backend`, `uses_cloud_backend`, `_should_use_cloud_mock`, `_build_cloud_llm`, `get_llm`, `get_judge_llm`, `get_coach_llm`, `coach_llm`, `unload_coach_llm`), `svc/llm.py` (`_max_concurrent`, `_SEMAPHORE`, `_uses_serial_lock`, `is_coach_loaded`, `unload_all`), `tests/conftest.py`, `tests/test_cloud_backend.py`, `.env.example`, `ANDROID-PLAN.md` (Phase 0).

---

### ADR 013: One account for training and coaching
* **Status**: Accepted
* **Decision**: A person may train and coach through one account. Player and coach are capabilities of that account, rather than exclusive identities. This avoids duplicate accounts and training histories for coaches who also train, while requiring authorization to check the current capability and coaching assignment for each action. An account cannot assign itself as its own coach. During the closed trial, only owner-invited accounts may gain the coach capability. A person may later disable coaching, ending their assignments while retaining their own training account.

---

### ADR 014: Consented assignment controls training-history access
* **Status**: Accepted
* **Decision**: A coach can read a player's training history only during an active, mutually consented assignment. Before accepting an invite, the player sees the access it grants. Every invite code is single-use and acts as the coach's advance authorization for its first redeemer; the code is not tied to a named recipient, so forwarding it can change who redeems it. The player must explicitly accept before immediate binding. Codes expire quickly, the coach receives an in-app and email notice on redemption, and the coach may immediately revoke the assignment. The email contains no training data. Revocation ends access to both current and earlier history. This avoids recipient verification for invites while limiting each code to one assignment.

---

### ADR 015: Durable account identity and deletion
* **Status**: Accepted
* **Decision**: Each account has an immutable identity distinct from its reusable username. JWT subjects identify the immutable account, while current capabilities and the session epoch are checked in the durable registry before any ledger is opened; a missing or deleted account fails closed. Account deletion invalidates sessions there, removes the live ledger and user-specific backup copies, and prevents an old token or restored backup from recreating the deleted identity. A former username may be registered again only as a new account. Fly volume snapshots are disabled; restricted whole-catalog recovery backups may retain deleted rows for up to 30 days, as disclosed to users. Every restore reapplies a durable deletion record kept outside the restored snapshot. This separates identity and revocation from the ledger being deleted while preserving username reuse and bounded disaster recovery.

---

### ADR 016: Minimize data sent to hosted models
* **Status**: Accepted
* **Decision**: The closed trial discloses hosted AI processing before use. Player inference receives the user's message and only the context needed to answer it; coach inference receives only the selected player's necessary telemetry, without account names or contact details, and never receives player-assistant chat. Coach-assistant exchanges are kept in memory for one selected player and are cleared on player switch, revocation, logout, or app close; the service does not persist a coach-assistant transcript in the trial. This permits hosted inference for the Android service while limiting unnecessary disclosure and cross-player context. User-written free text may still contain identifying information and must be described honestly in the privacy notice.

---

### ADR 017: Flutter is the product client
* **Status**: Accepted
* **Decision**: MAYOS is migrating to a mobile application, beginning with Android only for the closed trial. The Flutter app is the product client, backed by the FastAPI service; the Streamlit interface is legacy migration reference and serves no users. Delete it after the four-week trial passes its exit gates and opted-in real-user imports finish, before public launch. The local GGUF backend remains available for development and evaluation. This concentrates delivery and design work on one user experience while retaining useful engine test paths.

---

### ADR 018: Coach applies substitutions to coach-controlled programs
* **Status**: Accepted
* **Decision**: After a coach publishes a player's program, the player requests an exercise substitution and the coach applies any replacement. Existing player-side substitution paths must become requests for coach-controlled programs; the coach owns the resulting program change. A request can be applied, declined with a short player-visible reason, or cancelled. Recording a skipped or unplanned exercise truthfully in a workout is allowed and does not change the program; the coach sees that divergence while assigned. This preserves the coach's responsibility for the program without falsifying the player's workout history. Self-service remains available before coach publication and after assignment revocation.

---

### ADR 019: Opt-in import of existing training history
* **Status**: Accepted
* **Decision**: The mobile service does not bulk-import every local ledger. Existing real users may explicitly opt into an audited import of their histories, receive new immutable account IDs, and complete a secure account-claim path. Local ledgers include development and test data, mixed schema versions, and mostly lack password credentials, so automatic import would risk creating unwanted or insecure cloud accounts. The import uses consistent SQLite snapshots and verifies record counts before cutover.

---

### ADR 020: Offline workout drafts with idempotent sync
* **Status**: Accepted
* **Decision**: The Android player may capture workout drafts without connectivity and sync them when connected. Chat and program changes remain online. Each draft carries a stable client session ID, performed date and timezone, and the program version used while logging; server commit must be idempotent so retries cannot create duplicate workouts. If a coach publishes a newer program before sync, the workout remains a historical record against the captured version and does not change the new program; both parties see the version difference. Unsynced drafts survive app restart and logout in protected storage isolated to that account, with a logout warning and explicit discard action. Account deletion erases drafts on the deleting device; another offline device erases them when it next checks account status. Performed dates may be entered or corrected up to three days back, while upload/edit timestamps remain available for audit and affected absence alerts are recalculated. This adds a sync contract to the current online-only workout endpoint because workout logging is a core mobile task even when connectivity is interrupted.
